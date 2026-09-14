from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
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
    # this yet (my-service-template doesn't exist), but revendor() and
    # remote_stale() already sweep SERVICE_HARNESS.md alongside HARNESS.md so
    # the gate is ready the moment a service starts vendoring it.
    return files("mythings").joinpath("service-harness.md").read_text(encoding="utf-8")


# filename -> the canonical text a vendored copy of it must match.
_CANONICAL_BY_FILENAME: dict[str, Callable[[], str]] = {
    "HARNESS.md": harness_text,
    "SERVICE_HARNESS.md": service_harness_text,
}


# Editing harness.md (or service-harness.md) used to mean hand-copying it into
# every sibling repo; `python -m mythings._harness <workspace>` does that
# sweep in one command. Only repos that already vendor the given filename are
# touched — it never creates one, so checkouts that don't vendor it are left
# alone.


def revendor(
    workspace: Path, *, check: bool = False, filename: str = "HARNESS.md"
) -> tuple[list[str], list[str]]:
    canonical = _CANONICAL_BY_FILENAME[filename]()
    stale: list[str] = []
    fresh: list[str] = []
    for target in sorted(workspace.glob(f"*/{filename}")):
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
# re-vendoring 40-odd sibling repos cannot happen in one commit.
#
# Which is why "stale" cannot mean "its default branch disagrees". A sibling's
# sweep PR can only be written against the *new* canonical, so it is red until
# the core PR merges -- while the core PR, gated on that sibling's default
# branch, is red until the sweep merges. Neither can go green first, and the
# gate deadlocks the one change that would satisfy it. (Observed, not
# hypothetical: this gate's own first CI run failed exactly this way.)
#
# So a sibling counts as handled when its default branch already matches *or*
# an open PR on it carries a matching copy. The sweep must exist and be
# visible; it just doesn't have to have landed yet. A repo with no fix anywhere
# is what fails the gate.


@dataclass(frozen=True)
class VendorDrift:
    stale: list[str]  # no matching copy on the default branch or in any open PR
    in_flight: list[str]  # an open PR carries the matching copy; not yet merged
    current: list[str]


def _vendored_at(
    runner: Runner, org: str, name: str, ref: str | None = None, *, filename: str = "HARNESS.md"
) -> str:
    path = f"repos/{org}/{name}/contents/{filename}"
    if ref is not None:
        path += f"?ref={ref}"
    return runner(["api", path, "-H", "Accept: application/vnd.github.raw"])


def _sweep_in_flight(
    runner: Runner, org: str, name: str, canonical: str, *, filename: str = "HARNESS.md"
) -> bool:
    try:
        raw = runner(
            ["pr", "list", "--repo", f"{org}/{name}", "--state", "open",
             "--json", "headRefOid", "--limit", "50"]
        )
    except GitHubError:
        return False
    for pr in json.loads(raw):
        sha = str(pr.get("headRefOid", ""))
        if not sha:
            continue
        try:
            if _vendored_at(runner, org, name, sha, filename=filename) == canonical:
                return True
        except GitHubError:
            continue
    return False


def remote_stale(org: str, *, runner: Runner = _gh, filename: str = "HARNESS.md") -> VendorDrift:
    canonical = _CANONICAL_BY_FILENAME[filename]()
    drift = VendorDrift(stale=[], in_flight=[], current=[])
    raw = runner(["repo", "list", org, "--json", "name,isArchived", "--limit", "300"])
    for entry in sorted(json.loads(raw), key=lambda e: str(e.get("name", ""))):
        # An archived repo is read-only -- it cannot be re-vendored, so holding
        # a core change hostage to it would make the gate permanently red.
        if entry.get("isArchived"):
            continue
        name = str(entry["name"])
        try:
            vendored = _vendored_at(runner, org, name, filename=filename)
        except GitHubError:
            continue  # doesn't vendor this file; not this gate's business
        if vendored == canonical:
            drift.current.append(name)
        elif _sweep_in_flight(runner, org, name, canonical, filename=filename):
            drift.in_flight.append(name)
        else:
            drift.stale.append(name)
    return drift


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
        "workspace; exit 1 if any vendored copy is stale",
    )
    parser.add_argument(
        "--filename",
        choices=sorted(_CANONICAL_BY_FILENAME),
        default="HARNESS.md",
        help="which canonical file to sweep/check (default: HARNESS.md)",
    )
    args = parser.parse_args(argv)

    if args.remote_check:
        drift = remote_stale(args.remote_check, filename=args.filename)
        for name in drift.in_flight:
            print(f"sweep in flight: {name}/{args.filename} (open PR carries the new copy)")
        for name in drift.stale:
            print(f"stale: {name}/{args.filename}")
        print(
            f"{len(drift.stale)} stale, {len(drift.in_flight)} in flight, "
            f"{len(drift.current)} already current"
        )
        return 1 if drift.stale else 0

    if args.workspace is None:
        parser.error("give a workspace path, or --remote-check ORG")

    stale, fresh = revendor(args.workspace, check=args.check, filename=args.filename)
    verb = "stale" if args.check else "re-vendored"
    for name in stale:
        print(f"{verb}: {name}/{args.filename}")
    print(f"{len(stale)} {verb}, {len(fresh)} already current")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
