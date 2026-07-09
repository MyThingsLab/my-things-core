from __future__ import annotations

import argparse
import ast
import importlib
from dataclasses import dataclass, field
from pathlib import Path

import mythings
from mythings import _manifest

# Core-API coherence. Every tool declares what it needs from core in
# tools_manifest.json's `depends_on` ("core:<attr>"), and every tool's source
# imports symbols from `mythings`. Nothing verified either claim: tools float on
# `my-things-core @ git+...@main`, so the day core renames a public symbol,
# thirty repos break silently, one CI run at a time.
#
# Build tooling, not a contract — deliberately not exported from the package,
# mirroring _harness and _manifest.


@dataclass(frozen=True)
class Report:
    errors: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: Report) -> Report:
        return Report(
            errors=[*self.errors, *other.errors],
            pending=[*self.pending, *other.pending],
            notes=[*self.notes, *other.notes],
        )


def resolves(attr: str) -> bool:
    # A `core:<attr>` claim is satisfied by a public export, a module-level name
    # in mythings.github, or a method on the GitHub client — the three places
    # the manifest's existing claims (diff, repo_list, repo_create, …) point at.
    if hasattr(mythings, attr):
        return True
    try:
        github = importlib.import_module("mythings.github")
    except ImportError:  # pragma: no cover - core always ships github
        return False
    return hasattr(github, attr) or hasattr(github.GitHub, attr)


def check_claims(entries: list[_manifest.ToolEntry] | None = None) -> Report:
    # A shipped tool whose core claim is unmet is a regression: either core
    # dropped the capability, or the tool shipped without its prerequisite.
    # An unbuilt tool's unmet claim is the prerequisite itself — the whole point
    # of recording it — so it is reported, never fatal.
    tools = entries if entries is not None else _manifest.load_tools()
    known = {tool.repo for tool in tools}
    report = Report()

    for tool in sorted(tools, key=lambda t: t.repo):
        for dep in tool.depends_on:
            prefix, _, target = dep.partition(":")
            if prefix == "core":
                if resolves(target):
                    continue
                line = f"{tool.repo} needs core:{target}, which core does not provide"
                if tool.status == "shipped":
                    report.errors.append(line)
                else:
                    report.pending.append(f"{line} (tool is {tool.status})")
            elif prefix == "tool":
                if target not in known:
                    report.errors.append(f"{tool.repo} depends on tool:{target}, not in the fleet")
                    continue
                dependency = next(t for t in tools if t.repo == target)
                if tool.status == "shipped" and dependency.status != "shipped":
                    report.errors.append(
                        f"{tool.repo} is shipped but depends on tool:{target}, "
                        f"which is only {dependency.status}"
                    )
            else:
                report.errors.append(f"{tool.repo} has an unreadable dependency: {dep!r}")
    return report


def _imported_symbols(source: Path) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mythings"):
            found.extend((node.module, alias.name) for alias in node.names)
    return found


def check_imports(workspace: Path, entries: list[_manifest.ToolEntry] | None = None) -> Report:
    # The manifest's depends_on is a declaration; this is the ground truth.
    # Every `from mythings… import X` in a shipped tool must resolve against the
    # core that is actually installed.
    tools = entries if entries is not None else _manifest.load_tools()
    shipped = [t.repo for t in tools if t.status == "shipped"]
    report = Report()
    checked = 0

    for repo in sorted(shipped):
        source_root = workspace / repo / "src"
        if not source_root.is_dir():
            report.notes.append(f"{repo}: no local checkout, skipped")
            continue
        for module_file in sorted(source_root.rglob("*.py")):
            for module_name, symbol in _imported_symbols(module_file):
                try:
                    module = importlib.import_module(module_name)
                except ImportError:
                    report.errors.append(f"{repo}/{module_file.name} imports missing {module_name}")
                    continue
                if hasattr(module, symbol):
                    checked += 1
                else:
                    report.errors.append(
                        f"{repo}/{module_file.name} imports {module_name}.{symbol}, "
                        "which core no longer provides"
                    )
    report.notes.append(f"{checked} symbol imports resolved across {len(shipped)} shipped tools")
    return report


def _core_checkout(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "src" / "mythings" / "__init__.py").is_file():
            return candidate
    return None


def check_environment(cwd: Path | None = None) -> Report:
    # The shared .venv installs core editable from one checkout. Work inside a
    # git worktree of core and `import mythings` still resolves to the *other*
    # tree — so a manifest entry you just added is invisible, and a check you
    # just wrote silently tests the wrong source. Catch that explicitly.
    report = Report()
    resolved = Path(mythings.__file__).resolve().parent
    report.notes.append(f"mythings {mythings.__version__} resolves to {resolved}")

    here = (cwd or Path.cwd()).resolve()
    checkout = _core_checkout(here)
    if checkout is None:
        return report

    expected = (checkout / "src" / "mythings").resolve()
    if resolved != expected:
        report.errors.append(
            f"you are working in the core checkout at {checkout}, but `import mythings` "
            f"resolves to {resolved} — the installed core is a different tree, so edits "
            f"here are invisible. Re-run with PYTHONPATH={checkout / 'src'}, "
            f"or `pip install -e {checkout}`"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._compat",
        description="Check that the fleet's tools agree with the core they import.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="MyThingsLab workspace root; enables the import scan over sibling checkouts",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if any coherence error is found (pending claims never fail)",
    )
    args = parser.parse_args(argv)

    report = check_environment().merge(check_claims())
    if args.workspace is not None:
        report = report.merge(check_imports(args.workspace))

    for note in report.notes:
        print(f"  {note}")
    for line in report.pending:
        print(f"PENDING {line}")
    for line in report.errors:
        print(f"ERROR   {line}")
    print(f"{len(report.errors)} error(s), {len(report.pending)} pending claim(s)")
    return 1 if (args.check and report.errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
