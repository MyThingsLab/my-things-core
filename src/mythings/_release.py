from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

# The v1 release contract (semver, CHANGELOG, deprecation, pinning) ships as
# package data the same way harness.md does, and is vendored into each v1
# repo's RELEASE.md by the same sweep pattern as _harness.revendor. Build
# tooling, not a contract — deliberately not exported from the package,
# mirroring _harness and _compat.

_CHANGELOG_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)


class DynamicAllError(RuntimeError):
    pass


def _git(repo: Path, argv: list[str]) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def _module_dotted_name(rel_path: str) -> str:
    mod_path = rel_path.removeprefix("src/") if rel_path.startswith("src/") else rel_path
    mod_name = mod_path.replace("/", ".").removesuffix(".py")
    if mod_name.endswith(".__init__"):
        mod_name = mod_name.removesuffix(".__init__")
    return mod_name


def _literal_all_entries(tree: ast.Module) -> set[str] | None:
    # Last `__all__` assignment wins, matching normal Python name-binding
    # semantics for repeated assignment to the same module-level name.
    found: set[str] | None = None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not (isinstance(target, ast.Name) and target.id == "__all__"):
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            raise DynamicAllError("__all__ is not a literal list/tuple of string constants")
        names = []
        for elt in value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                raise DynamicAllError("__all__ is not a literal list/tuple of string constants")
            names.append(elt.value)
        found = set(names)
    return found


def public_surface_at_ref(repo: Path, ref: str) -> set[str]:
    listing = _git(repo, ["ls-tree", "-r", "--name-only", ref, "--", "src/mythings"])
    surface: set[str] = set()
    for rel_path in listing.splitlines():
        if not rel_path.endswith(".py"):
            continue
        source = _git(repo, ["show", f"{ref}:{rel_path}"])
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            continue
        try:
            entries = _literal_all_entries(tree)
        except DynamicAllError as exc:
            raise DynamicAllError(f"{rel_path} @ {ref}: {exc}") from exc
        if not entries:
            continue
        mod = _module_dotted_name(rel_path)
        surface |= {f"{mod}.{name}" for name in entries}
    return surface


def _pyproject_version_at_ref(repo: Path, ref: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:pyproject.toml"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    return tomllib.loads(proc.stdout).get("project", {}).get("version")


def _semver_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")[:3]
    return int(major), int(minor), int(patch)


def surface_delta_errors(repo: Path, base_ref: str, head_ref: str) -> list[str]:
    repo = Path(repo).resolve()
    base_surface = public_surface_at_ref(repo, base_ref)
    head_surface = public_surface_at_ref(repo, head_ref)
    added = head_surface - base_surface
    removed = base_surface - head_surface
    if not added and not removed:
        return []

    base_version = _pyproject_version_at_ref(repo, base_ref)
    head_version = _pyproject_version_at_ref(repo, head_ref)
    if base_version is None or head_version is None:
        return [
            f"{repo.name}: public surface changed between {base_ref} and {head_ref}, but "
            f"pyproject.toml version could not be read at one or both refs"
        ]

    base_semver = _semver_tuple(base_version)
    head_semver = _semver_tuple(head_version)
    errors: list[str] = []
    if added and (head_semver[0], head_semver[1]) <= (base_semver[0], base_semver[1]):
        errors.append(
            f"{repo.name}: public surface grew ({', '.join(sorted(added))}) but version "
            f"{base_version} -> {head_version} is not at least a MINOR bump"
        )
    if removed and head_semver[0] <= base_semver[0]:
        errors.append(
            f"{repo.name}: public surface shrank ({', '.join(sorted(removed))}) but version "
            f"{base_version} -> {head_version} is not a MAJOR bump"
        )
    return errors


def release_text() -> str:
    return files("mythings").joinpath("release.md").read_text(encoding="utf-8")


def revendor(workspace: Path, *, check: bool = False) -> tuple[list[str], list[str]]:
    canonical = release_text()
    stale: list[str] = []
    fresh: list[str] = []
    for target in sorted(workspace.glob("*/RELEASE.md")):
        if target.read_text(encoding="utf-8") == canonical:
            fresh.append(target.parent.name)
        else:
            if not check:
                target.write_text(canonical, encoding="utf-8")
            stale.append(target.parent.name)
    return stale, fresh


def _pyproject_version(repo: Path) -> str | None:
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _changelog_headings(repo: Path) -> list[str]:
    changelog = repo / "CHANGELOG.md"
    if not changelog.is_file():
        return []
    return _CHANGELOG_HEADING_RE.findall(changelog.read_text(encoding="utf-8"))


def check_version_changelog(repo: Path) -> list[str]:
    # No RELEASE.md gating here, unlike the workspace sweep below -- core
    # itself is a v1 repo that must satisfy this check too, but authors the
    # canonical release.md rather than vendoring a copy of it. Callers decide
    # which repos are in scope; this only ever checks the one it is given.
    version = _pyproject_version(repo)
    if version is None:
        return [f"{repo.name}: vendors RELEASE.md but has no pyproject.toml version"]
    headings = _changelog_headings(repo)
    errors = []
    if version not in headings:
        errors.append(
            f"{repo.name}: pyproject.toml declares version {version}, "
            f"no matching '## [{version}]' entry in CHANGELOG.md"
        )
    # A duplicate heading means two different commits both shipped as "the
    # same version" -- the tag for that version can then only ever name one
    # of them, so it silently stops identifying the other's code. Caught this
    # repo out once already (605cda5 and 89a3340 both claimed [1.2.0]).
    seen: set[str] = set()
    for heading in headings:
        if heading in seen:
            errors.append(
                f"{repo.name}: CHANGELOG.md has more than one '## [{heading}]' entry"
            )
        seen.add(heading)
    return errors


def check(workspace: Path) -> list[str]:
    errors: list[str] = []
    for repo in sorted(p.parent for p in workspace.glob("*/RELEASE.md")):
        errors.extend(check_version_changelog(repo))
    return errors


def _check_surface_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._release check-surface",
        description=(
            "Fail if the union of __all__ across src/mythings grew or shrank between "
            "two git refs without a matching semver bump in pyproject.toml."
        ),
    )
    parser.add_argument("base_ref", help="git ref to compare from, e.g. the last release tag")
    parser.add_argument("head_ref", help="git ref to compare to, e.g. the PR head SHA")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repo root (default: cwd)")
    args = parser.parse_args(argv)

    errors = surface_delta_errors(args.repo, args.base_ref, args.head_ref)
    for line in errors:
        print(f"ERROR   {line}")
    print(f"{len(errors)} surface/version mismatch(es)")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    # Bolted on rather than a proper argparse subcommand: `revendor`'s
    # `workspace` positional is the documented, fleet-wide invocation
    # (release.md tells every v1 repo to run `python -m mythings._release
    # <workspace-root>`), and subparsers would make that argv shape ambiguous
    # with `check-surface`'s. Dispatching on argv[0] keeps both shapes valid.
    raw_argv = sys.argv[1:] if argv is None else argv
    if raw_argv[:1] == ["check-surface"]:
        return _check_surface_main(raw_argv[1:])

    parser = argparse.ArgumentParser(
        prog="python -m mythings._release",
        description=(
            "Re-vendor the canonical release.md into every v1 repo's RELEASE.md, "
            "and check that each vendoring repo's version and CHANGELOG agree."
        ),
    )
    parser.add_argument(
        "workspace", type=Path, help="MyThingsLab workspace root (parent of the tool checkouts)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale copies and version/changelog mismatches without rewriting; exit if any",
    )
    args = parser.parse_args(argv)

    stale, fresh = revendor(args.workspace, check=args.check)
    verb = "stale" if args.check else "re-vendored"
    for name in stale:
        print(f"{verb}: {name}/RELEASE.md")
    print(f"{len(stale)} {verb}, {len(fresh)} already current")

    mismatches = check(args.workspace)
    for line in mismatches:
        print(f"ERROR   {line}")
    print(f"{len(mismatches)} version/changelog mismatch(es)")

    return 1 if (args.check and (stale or mismatches)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
