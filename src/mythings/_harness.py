from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path

from mythings.github import GitHubError, Runner, _gh

# The canonical build-harness rules ship as package data so any tool that
# installs my-things-core can diff its vendored HARNESS.md against this. Build
# tooling, not a contract — deliberately not exported from the package.


def harness_text() -> str:
    return files("mythings").joinpath("harness.md").read_text(encoding="utf-8")


def service_harness_text() -> str:
    # The long-running-process archetype (my-server, my-telegram-bot,
    # my-dashboard's serving mode) -- a distinct canonical harness, not a
    # variant of harness_text(), since its load-bearing invariants genuinely
    # differ (not issue-triggered, may not open a PR at all). No repo vendors
    # this yet; revendor()'s sweep stays scoped to HARNESS.md until a
    # my-service-template exists to vendor a SERVICE_HARNESS.md copy of it.
    return files("mythings").joinpath("service-harness.md").read_text(encoding="utf-8")


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


# `--check` against a workspace can only see the checkouts that happen to be on
# this disk, which in CI is none of them: core's own workflow checks out core
# alone, so the glob above matches nothing and the check passes trivially. A
# gate that cannot fail is worse than no gate, so the CI-facing check reads the
# vendored copies from GitHub instead of from a workspace.
#
# This is a real gate but not an atomic one: merging a harness.md edit and
# re-vendoring 40-odd sibling repos cannot happen in one commit. It fails the
# core PR that would strand them, which is the point -- the sweep lands first,
# or the edit waits.


def remote_stale(org: str, *, runner: Runner = _gh) -> tuple[list[str], list[str]]:
    canonical = harness_text()
    stale: list[str] = []
    fresh: list[str] = []
    raw = runner(["repo", "list", org, "--json", "name,isArchived", "--limit", "300"])
    for entry in sorted(json.loads(raw), key=lambda e: str(e.get("name", ""))):
        # An archived repo is read-only -- it cannot be re-vendored, so holding
        # a core change hostage to it would make the gate permanently red.
        if entry.get("isArchived"):
            continue
        name = str(entry["name"])
        try:
            vendored = runner(
                [
                    "api",
                    f"repos/{org}/{name}/contents/HARNESS.md",
                    "-H",
                    "Accept: application/vnd.github.raw",
                ]
            )
        except GitHubError:
            continue  # doesn't vendor a HARNESS.md; not this gate's business
        (fresh if vendored == canonical else stale).append(name)
    return stale, fresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._harness",
        description="Re-vendor the canonical harness.md into every sibling repo's HARNESS.md.",
    )
    parser.add_argument(
        "workspace",
        type=Path,
        nargs="?",
        help="MyThingsLab workspace root (parent of the tool checkouts)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale copies without rewriting; exit 1 if any is stale",
    )
    parser.add_argument(
        "--remote-check",
        metavar="ORG",
        help="check every non-archived repo in ORG on GitHub instead of a local "
        "workspace; exit 1 if any vendored HARNESS.md is stale",
    )
    args = parser.parse_args(argv)

    if args.remote_check:
        stale, fresh = remote_stale(args.remote_check)
    elif args.workspace is not None:
        stale, fresh = revendor(args.workspace, check=args.check)
    else:
        parser.error("give a workspace path, or --remote-check ORG")

    verb = "stale" if (args.check or args.remote_check) else "re-vendored"
    for name in stale:
        print(f"{verb}: {name}/HARNESS.md")
    print(f"{len(stale)} {verb}, {len(fresh)} already current")
    return 1 if ((args.check or args.remote_check) and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
