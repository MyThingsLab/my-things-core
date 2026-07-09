from pathlib import Path

from mythings._manifest import STATUSES, load_tools, resync

DOCS_TOOLS = Path(__file__).parent.parent / "docs" / "tools"


def test_manifest_loads_with_valid_entries() -> None:
    tools = load_tools()
    assert len(tools) >= 30
    repos = [t.repo for t in tools]
    assert len(repos) == len(set(repos)), "duplicate repo in tools_manifest.json"
    for t in tools:
        assert t.status in STATUSES, f"{t.repo}: bad status {t.status!r}"
        assert t.added and t.tool and t.package


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
        f"stale frontmatter in docs/tools: {stale} — "
        "re-sync with `python -m mythings._manifest docs/tools`"
    )
    assert fresh, "resync matched no docs — wrong docs dir?"


def test_shipped_docs_carry_the_historical_banner() -> None:
    unbannered = []
    for t in load_tools():
        doc = DOCS_TOOLS / f"{t.repo}.md"
        if t.status != "shipped" or not doc.exists():
            continue
        if "> **Historical.**" not in doc.read_text(encoding="utf-8"):
            unbannered.append(t.repo)
    assert not unbannered, f"shipped tools' docs missing the historical banner: {unbannered}"
