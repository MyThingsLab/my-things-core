from __future__ import annotations

import argparse
import re
import tomllib
from importlib.resources import files
from pathlib import Path

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


def _changelog_versions(repo: Path) -> set[str]:
    changelog = repo / "CHANGELOG.md"
    if not changelog.is_file():
        return set()
    return set(_CHANGELOG_HEADING_RE.findall(changelog.read_text(encoding="utf-8")))


def check_version_changelog(repo: Path) -> list[str]:
    # No RELEASE.md gating here, unlike the workspace sweep below -- core
    # itself is a v1 repo that must satisfy this check too, but authors the
    # canonical release.md rather than vendoring a copy of it. Callers decide
    # which repos are in scope; this only ever checks the one it is given.
    version = _pyproject_version(repo)
    if version is None:
        return [f"{repo.name}: vendors RELEASE.md but has no pyproject.toml version"]
    if version not in _changelog_versions(repo):
        return [
            f"{repo.name}: pyproject.toml declares version {version}, "
            f"no matching '## [{version}]' entry in CHANGELOG.md"
        ]
    return []


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
