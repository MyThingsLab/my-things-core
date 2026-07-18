import json
from pathlib import Path

import pytest

from mythings._manifest import STATUSES, ledger_kind_registry, load_tools, resync, tools_table

DOCS_TOOLS = Path(__file__).parent.parent / "docs" / "tools"


def _tool_stub(tool: str, repo: str, ledger_kinds: list[str]) -> dict:
    return {
        "tool": tool,
        "repo": repo,
        "package": repo.replace("-", ""),
        "title": "stub",
        "added": "2026-01-01",
        "status": "designed",
        "backlog_label": repo,
        "engine_call": "none",
        "ledger_kinds": ledger_kinds,
        "depends_on": [],
    }


def test_manifest_loads_with_valid_entries() -> None:
    tools = load_tools()
    assert len(tools) >= 30
    repos = [t.repo for t in tools]
    assert len(repos) == len(set(repos)), "duplicate repo in tools_manifest.json"
    for t in tools:
        assert t.status in STATUSES, f"{t.repo}: bad status {t.status!r}"
        assert t.added and t.tool and t.package


def test_web_app_defaults_to_none_when_omitted() -> None:
    tools = load_tools(json.dumps([_tool_stub("MyAlpha", "my-alpha", [])]))
    assert tools[0].web_app is None


def test_my_server_declares_a_local_web_app() -> None:
    tools = {t.repo: t for t in load_tools()}
    assert tools["my-server"].web_app == {
        "run": "myserver serve",
        "port": 8787,
        "hosted_url": None,
    }


def test_depends_on_refs_resolve() -> None:
    tools = load_tools()
    repos = {t.repo for t in tools}
    for t in tools:
        for dep in t.depends_on:
            prefix, _, name = dep.partition(":")
            assert prefix in ("tool", "core"), f"{t.repo}: bad dep prefix {dep!r}"
            assert name, f"{t.repo}: empty dep name in {dep!r}"
            if prefix == "tool":
                assert name in repos, f"{t.repo}: depends on unknown tool {name!r}"


def test_every_design_doc_has_a_manifest_entry() -> None:
    repos = {t.repo for t in load_tools()}
    docs = {p.stem for p in DOCS_TOOLS.glob("my-*.md")}
    missing = docs - repos
    assert not missing, f"design docs without a tools_manifest.json entry: {sorted(missing)}"


def test_doc_frontmatter_matches_manifest() -> None:
    stale, fresh = resync(DOCS_TOOLS, check=True)
    assert not stale, (
        f"stale frontmatter or README table in docs/tools: {stale} — "
        "re-sync with `python -m mythings._manifest docs/tools`"
    )
    assert fresh, "resync matched no docs — wrong docs dir?"


def test_tools_table_skips_repos_without_a_design_doc() -> None:
    table = tools_table(DOCS_TOOLS)
    assert "my-guard.md" not in table, "my-guard has no design doc; it must not get a row"
    assert "[my-tester.md](my-tester.md)" in table


def test_tools_table_has_no_rows_when_no_entry_has_a_doc() -> None:
    stub = load_tools(json.dumps([_tool_stub("MyAlpha", "my-alpha", [])]))
    table = tools_table(DOCS_TOOLS, stub)
    assert table == "| Tool | One line | Engine call | Doc |\n|---|---|---|---|"


def test_shipped_docs_carry_the_historical_banner() -> None:
    unbannered = []
    for t in load_tools():
        doc = DOCS_TOOLS / f"{t.repo}.md"
        if t.status != "shipped" or not doc.exists():
            continue
        if "> **Historical.**" not in doc.read_text(encoding="utf-8"):
            unbannered.append(t.repo)
    assert not unbannered, f"shipped tools' docs missing the historical banner: {unbannered}"


def test_ledger_kind_registry_is_collision_free_in_shipped_manifest() -> None:
    registry = ledger_kind_registry()
    all_kinds = [k for t in load_tools() for k in t.ledger_kinds]
    # Every declared kind is registered, and to exactly one owning tool.
    assert sorted(registry) == sorted(all_kinds)
    assert len(registry) == len(all_kinds), "a ledger kind is claimed by two tools"


def test_ledger_kind_registry_raises_on_collision() -> None:
    text = json.dumps(
        [
            _tool_stub("MyAlpha", "my-alpha", ["shared_kind"]),
            _tool_stub("MyBeta", "my-beta", ["shared_kind"]),
        ]
    )
    with pytest.raises(ValueError, match="duplicate ledger kind 'shared_kind'"):
        ledger_kind_registry(text)
