from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

# The canonical fleet registry — one entry per My[X] tool (designed, building,
# or shipped) — ships as package data so every consumer (MyOrchestrator's
# scaffold candidates, MyProjector, the docs index) reads the same file instead
# of re-deriving or hand-copying it. Build tooling, not a contract —
# deliberately not exported from the package, mirroring _harness.


@dataclass(frozen=True)
class ToolEntry:
    tool: str  # design name, e.g. "MyTester"
    repo: str  # target repo / collision key, e.g. "my-tester"
    package: str  # import package, e.g. "mytester"
    title: str  # the one-line description from the docs index
    added: str  # ISO date the proposal was recorded; the oldest-first key
    status: str  # "designed" | "building" | "shipped"
    backlog_label: str  # the GitHub issue label the tool picks up
    engine_call: str  # the single Engine call, or "none…" / "optional: …"
    ledger_kinds: list[str]  # the runtime-Ledger kinds this tool writes
    depends_on: list[str]  # "tool:<repo>" (built) or "core:<github.GitHub attr>"
    # Optional: set once a tool ships a local server. `hosted_url` stays null
    # until the tool is actually deployed somewhere reachable — that's a
    # separate, later decision (hosting, auth, exposure beyond localhost).
    web_app: dict | None = None
    # Optional, machine-checkable JSON-Schema fragments for the tool's CLI
    # args / ledger `data` payload. Null until authored — backfilled
    # opportunistically as a tool is touched, not required fleet-wide.
    input_schema: dict | None = None
    output_schema: dict | None = None


STATUSES = ("designed", "building", "shipped")


def manifest_text() -> str:
    return files("mythings").joinpath("tools_manifest.json").read_text(encoding="utf-8")


def load_tools(text: str | None = None) -> list[ToolEntry]:
    return [ToolEntry(**obj) for obj in json.loads(text if text is not None else manifest_text())]


def ledger_kind_registry(text: str | None = None) -> dict[str, str]:
    # The runtime-Ledger `kind` registry, derived from the manifest's per-tool
    # `ledger_kinds` (no separate file): maps each kind to the tool that owns
    # it. Cross-tool consumers (MyReporter, MyDashboard, MyOrchestrator, the
    # notify path) can discover the kinds that exist instead of hard-coding the
    # strings they understand. Self-guarding: a kind declared by two tools is a
    # collision -- the exact class of bug the MyWiki/MyKnowledger rename existed
    # to avoid -- and raises here, so the manifest-integrity test (and thus CI)
    # fails the moment a new tool reuses an existing kind.
    owners: dict[str, str] = {}
    for entry in load_tools(text):
        for kind in entry.ledger_kinds:
            if kind in owners:
                raise ValueError(
                    f"duplicate ledger kind {kind!r}: declared by both "
                    f"{owners[kind]} and {entry.tool} — kinds must be unique across the fleet"
                )
            owners[kind] = entry.tool
    return owners


# Each design doc under docs/tools/ carries this frontmatter block so the doc
# set stays queryable; the manifest is canonical and the blocks are generated
# from it. `python -m mythings._manifest <docs-dir>` re-syncs them in one
# command (--check reports drift instead, for CI), mirroring _harness's
# re-vendor sweep.


def frontmatter_block(entry: ToolEntry) -> str:
    def lst(values: list[str]) -> str:
        return "[" + ", ".join(values) + "]"

    return (
        "---\n"
        f"tool: {entry.tool}\n"
        f"repo: {entry.repo}\n"
        f"package: {entry.package}\n"
        f"status: {entry.status}\n"
        f"added: {entry.added}\n"
        f"backlog_label: {entry.backlog_label}\n"
        f"engine_call: {entry.engine_call}\n"
        f"ledger_kinds: {lst(entry.ledger_kinds)}\n"
        f"depends_on: {lst(entry.depends_on)}\n"
        "---\n"
    )


def _with_frontmatter(text: str, block: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1:
            raise ValueError("unterminated frontmatter block")
        text = text[end + len("\n---\n") :].lstrip("\n")
    return block + "\n" + text


# The README's "The tools" table is the other hand-maintained duplicate of the
# manifest (frontmatter blocks were the first, resynced above). Only tools
# with a design doc get a row — a manifest entry with no docs/tools/<repo>.md
# (my-guard, MyCoder, ...) has nothing for the "Doc" column to link to and is
# covered elsewhere in the page (prose, or the "MyCoder (deferred)" stub).
TABLE_BEGIN = "<!-- manifest:begin -->"
TABLE_END = "<!-- manifest:end -->"


def tools_table(docs_dir: Path, entries: list[ToolEntry] | None = None) -> str:
    tools = entries if entries is not None else load_tools()
    rows = [
        f"| {e.tool} | {e.title} | {e.engine_call} | [{e.repo}.md]({e.repo}.md) |"
        for e in tools
        if (docs_dir / f"{e.repo}.md").exists()
    ]
    return "\n".join(["| Tool | One line | Engine call | Doc |", "|---|---|---|---|", *rows])


def _with_table(text: str, table: str) -> str:
    start = text.find(TABLE_BEGIN)
    end = text.find(TABLE_END)
    if start == -1 or end == -1:
        raise ValueError(f"README missing {TABLE_BEGIN}/{TABLE_END} markers")
    return f"{text[: start + len(TABLE_BEGIN)]}\n{table}\n{text[end:]}"


def resync(docs_dir: Path, *, check: bool = False) -> tuple[list[str], list[str]]:
    stale: list[str] = []
    fresh: list[str] = []
    tools = load_tools()
    for entry in tools:
        doc = docs_dir / f"{entry.repo}.md"
        if not doc.exists():
            continue
        block = frontmatter_block(entry)
        text = doc.read_text(encoding="utf-8")
        wanted = _with_frontmatter(text, block)
        if text == wanted:
            fresh.append(entry.repo)
        else:
            if not check:
                doc.write_text(wanted, encoding="utf-8")
            stale.append(entry.repo)

    readme = docs_dir / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        wanted = _with_table(text, tools_table(docs_dir, tools))
        if text == wanted:
            fresh.append("README")
        else:
            if not check:
                readme.write_text(wanted, encoding="utf-8")
            stale.append("README")
    return stale, fresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._manifest",
        description=(
            "Re-sync each design doc's frontmatter, and the README's tools table, "
            "from the canonical tools manifest."
        ),
    )
    parser.add_argument(
        "docs_dir", type=Path, help="the docs/tools directory holding the my-*.md design docs"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale frontmatter without rewriting; exit 1 if any is stale",
    )
    args = parser.parse_args(argv)

    stale, fresh = resync(args.docs_dir, check=args.check)
    verb = "stale" if args.check else "re-synced"
    for name in stale:
        print(f"{verb}: {name}.md")
    print(f"{len(stale)} {verb}, {len(fresh)} already current")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
