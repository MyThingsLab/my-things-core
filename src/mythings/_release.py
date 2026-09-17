from __future__ import annotations

import argparse
import ast
import re
import subprocess
import tomllib
from importlib.resources import files
from pathlib import Path, PurePosixPath

# The v1 release contract (semver, CHANGELOG, deprecation, pinning) ships as
# package data the same way harness.md does, and is vendored into each v1
# repo's RELEASE.md by the same sweep pattern as _harness.revendor. Build
# tooling, not a contract — deliberately not exported from the package,
# mirroring _harness and _compat.

_CHANGELOG_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)


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


# --- public-surface vs. semver ------------------------------------------
#
# check_version_changelog only asks whether a bump and its CHANGELOG agree; it
# says nothing about whether a bump was *warranted*. #202 merged six new
# `mythings.contract` exports with the version left at 1.7.0 and an existing
# [1.7.0] heading, so it agreed with itself all the way to main -- and v1
# consumers pin an exact tag, so the new module was unreachable. The baseline
# here is the latest release tag rather than the PR's base branch precisely
# because of that case: by the time a second PR arrives, an unbumped addition
# is already on main and a base-branch diff would call it pre-existing.


class SurfaceError(Exception):
    pass


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _targets_all(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__all__"


def module_exports(source: str, *, origin: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SurfaceError(f"{origin}: cannot parse module ({exc})") from exc

    # Scan the whole tree before reading any value. Returning on the first
    # literal would miss a later `+=` or a conditional rebind, and silently
    # under-reporting the surface is the one failure this check cannot afford.
    assignments: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and _targets_all(node.target):
            raise SurfaceError(
                f"{origin}: __all__ is assembled with '+='; the surface check reads "
                f"only a single literal list. Declare it as one literal."
            )
        if isinstance(node, ast.Assign) and any(_targets_all(t) for t in node.targets):
            assignments.append(node.value)
        elif isinstance(node, ast.AnnAssign) and _targets_all(node.target) and node.value:
            assignments.append(node.value)

    top_level = {id(n.value) for n in tree.body if isinstance(n, ast.Assign | ast.AnnAssign)}
    if any(id(value) not in top_level for value in assignments):
        raise SurfaceError(
            f"{origin}: __all__ is assigned conditionally or inside a nested scope; "
            f"the surface check reads only a single module-level literal."
        )
    if not assignments:
        return []

    # Last wins, matching Python's own rebinding semantics.
    try:
        literal = ast.literal_eval(assignments[-1])
    except (ValueError, SyntaxError) as exc:
        raise SurfaceError(
            f"{origin}: __all__ is computed, not a literal; the surface check "
            f"cannot resolve it without importing the module ({exc})"
        ) from exc
    if not isinstance(literal, list | tuple) or not all(isinstance(n, str) for n in literal):
        raise SurfaceError(f"{origin}: __all__ is not a list of strings")
    return list(literal)


def _module_name(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_private(module: str) -> bool:
    # _devledger, _harness, _release and friends are build tooling, not surface
    # -- core's CLAUDE.md says so explicitly and forbids exporting them.
    return any(part.startswith("_") for part in module.split("."))


def surface(sources: dict[str, str]) -> set[str]:
    # Qualified, not flat: a consumer pinning a tag cannot write
    # `from mythings import Criterion` until it appears in the top-level
    # __all__, even if mythings.contract exported it all along. That promotion
    # is new reachable surface and has to count as one.
    names: set[str] = set()
    for path, text in sorted(sources.items()):
        module = _module_name(path)
        if not module or _is_private(module):
            continue
        for name in module_exports(text, origin=path):
            names.add(f"{module}.{name}")
    return names


def _parse_version(version: str, *, label: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(version.strip())
    if match is None:
        raise SurfaceError(f"{label}: {version!r} is not MAJOR.MINOR.PATCH")
    return int(match[1]), int(match[2]), int(match[3])


def bump_kind(old: str, new: str) -> str | None:
    before = _parse_version(old, label="baseline version")
    after = _parse_version(new, label="version")
    if after < before:
        raise SurfaceError(f"version went backwards: {old} -> {new}")
    if after == before:
        return None
    if after[0] != before[0]:
        return "major"
    if after[1] != before[1]:
        return "minor"
    return "patch"


def surface_bump_errors(
    *,
    baseline: set[str],
    head: set[str],
    baseline_version: str,
    head_version: str,
    baseline_label: str,
) -> list[str]:
    added = sorted(head - baseline)
    removed = sorted(baseline - head)
    if not added and not removed:
        return []

    actual = bump_kind(baseline_version, head_version)
    if removed and actual != "major":
        return [
            f"public surface shrank since {baseline_label} but version is "
            f"{head_version} ({actual or 'unchanged'}); removing an export is MAJOR "
            f"per RELEASE.md. Removed: {', '.join(removed)}"
        ]
    if added and actual not in ("major", "minor"):
        return [
            f"public surface grew since {baseline_label} but version is "
            f"{head_version} ({actual or 'unchanged'}); a new export is MINOR "
            f"per RELEASE.md. Added: {', '.join(added)}"
        ]
    return []


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def latest_release_tag(repo: Path) -> str | None:
    out = _git(repo, "tag", "--list", "v[0-9]*", "--sort=-v:refname")
    tags = [line.strip() for line in out.splitlines() if line.strip()]
    return tags[0] if tags else None


def sources_at(repo: Path, rev: str) -> dict[str, str]:
    listing = _git(repo, "ls-tree", "-r", "--name-only", rev, "--", "src")
    sources: dict[str, str] = {}
    for path in listing.splitlines():
        path = path.strip()
        if path.endswith(".py"):
            sources[path] = _git(repo, "show", f"{rev}:{path}")
    return sources


def _worktree_sources(repo: Path) -> dict[str, str]:
    return {
        str(p.relative_to(repo).as_posix()): p.read_text(encoding="utf-8")
        for p in sorted((repo / "src").rglob("*.py"))
    }


def check_surface(repo: Path) -> list[str]:
    tag = latest_release_tag(repo)
    if tag is None:
        # Nothing released yet, so there is no surface a consumer could have
        # pinned. Not a violation.
        return []
    head_version = _pyproject_version(repo)
    if head_version is None:
        return [f"{repo.name}: no pyproject.toml version to compare against {tag}"]
    try:
        errors = surface_bump_errors(
            baseline=surface(sources_at(repo, tag)),
            head=surface(_worktree_sources(repo)),
            baseline_version=tag.lstrip("v"),
            head_version=head_version,
            baseline_label=tag,
        )
    except SurfaceError as exc:
        return [f"{repo.name}: {exc}"]
    return [f"{repo.name}: {line}" for line in errors]


def check(workspace: Path) -> list[str]:
    errors: list[str] = []
    for repo in sorted(p.parent for p in workspace.glob("*/RELEASE.md")):
        errors.extend(check_version_changelog(repo))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._release",
        description=(
            "Re-vendor the canonical release.md into every v1 repo's RELEASE.md, "
            "and check that each vendoring repo's version and CHANGELOG agree."
        ),
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        type=Path,
        help="MyThingsLab workspace root (parent of the tool checkouts)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale copies and version/changelog mismatches without rewriting; exit if any",
    )
    parser.add_argument(
        "--check-surface",
        type=Path,
        metavar="REPO",
        help="check one repo's public __all__ surface against its latest release tag; exit if the"
        " delta and the version bump disagree",
    )
    args = parser.parse_args(argv)

    # Its own mode: this one takes a single repo, not a workspace of them, and
    # is what CI runs per-PR.
    if args.check_surface is not None:
        repo = args.check_surface.resolve()
        tag = latest_release_tag(repo)
        if tag is None:
            print(f"{repo.name}: no release tag yet; nothing to compare a surface against")
            return 0
        violations = check_surface(repo)
        for line in violations:
            print(f"ERROR   {line}")
        if not violations:
            print(f"{repo.name}: public surface agrees with the version bump since {tag}")
        return 1 if violations else 0

    if args.workspace is None:
        parser.error("workspace is required unless --check-surface is given")

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
