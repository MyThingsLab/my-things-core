from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

# The canonical build-harness rules ship as package data so any tool that
# installs my-things-core can diff its vendored HARNESS.md against this. Build
# tooling, not a contract — deliberately not exported from the package.


def harness_text() -> str:
    return files("mythings").joinpath("harness.md").read_text(encoding="utf-8")


# Editing harness.md used to mean hand-copying it into every sibling repo;
# `python -m mythings._harness <workspace>` does that sweep in one command.
# Only repos that already vendor a HARNESS.md are touched — it never creates
# one, so non-tool checkouts in the workspace are left alone.


def revendor(workspace: Path, *, check: bool = False) -> tuple[list[str], list[str]]:
    canonical = harness_text()
    stale: list[str] = []
    fresh: list[str] = []
    for target in sorted(workspace.glob("*/HARNESS.md")):
        if target.read_text(encoding="utf-8") == canonical:
            fresh.append(target.parent.name)
        else:
            if not check:
                target.write_text(canonical, encoding="utf-8")
            stale.append(target.parent.name)
    return stale, fresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._harness",
        description="Re-vendor the canonical harness.md into every sibling repo's HARNESS.md.",
    )
    parser.add_argument(
        "workspace", type=Path, help="MyThingsLab workspace root (parent of the tool checkouts)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale copies without rewriting; exit 1 if any is stale",
    )
    args = parser.parse_args(argv)

    stale, fresh = revendor(args.workspace, check=args.check)
    verb = "stale" if args.check else "re-vendored"
    for name in stale:
        print(f"{verb}: {name}/HARNESS.md")
    print(f"{len(stale)} {verb}, {len(fresh)} already current")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
