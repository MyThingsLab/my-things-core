"""Tests for mythings.handoff — inter-tool handoff contract."""

from pathlib import Path

from mythings.handoff import (
    StageHandoff,
    handoffs_dir,
    load_latest_handoff,
    save_handoff,
)


def test_handoff_serialization_roundtrip():
    h = StageHandoff(
        stage="coder",
        target_issue="my-coder#44",
        repo_name="my-coder",
        goal_id="goal-1",
        target_symbols=["symbol:mycoder.coder.Coder"],
        modified_files=["src/mycoder/coder.py"],
        test_targets=["tests/test_coder.py"],
        context_pack_md="## Context Pack Scope",
        assertions_passed=5,
        assertions_failed=0,
    )

    d = h.to_dict()
    assert d["stage"] == "coder"
    assert d["target_issue"] == "my-coder#44"

    json_str = h.to_json()
    reconstructed = StageHandoff.from_json(json_str)
    assert reconstructed.stage == h.stage
    assert reconstructed.target_issue == h.target_issue
    assert reconstructed.target_symbols == h.target_symbols
    assert reconstructed.assertions_passed == 5


def test_render_prompt_slice():
    h = StageHandoff(
        stage="coder",
        target_issue="my-coder#44",
        repo_name="my-coder",
        goal_id="goal-123",
        target_symbols=["symbol:coder.main"],
        modified_files=["src/coder/cli.py"],
        test_targets=["tests/test_cli.py"],
        assertions_passed=3,
        assertions_failed=0,
    )

    rendered = h.render_prompt_slice()
    assert "Inter-Tool Handoff (`coder` → next stage)" in rendered
    assert "`my-coder#44`" in rendered
    assert "`goal-123`" in rendered
    assert "`symbol:coder.main`" in rendered
    assert "3 passed" in rendered


def test_save_and_load_handoff(tmp_path: Path):
    h1 = StageHandoff(
        stage="researcher",
        target_issue="my-fleet#80",
        repo_name="my-fleet",
        target_symbols=["symbol:fleet_audit.main"],
    )
    saved_path = save_handoff(tmp_path, h1)
    assert saved_path.exists()
    assert handoffs_dir(tmp_path).exists()

    loaded = load_latest_handoff(tmp_path, "my-fleet#80", stage="researcher")
    assert loaded is not None
    assert loaded.stage == "researcher"
    assert loaded.target_symbols == ["symbol:fleet_audit.main"]


def test_load_latest_handoff_returns_none_if_missing(tmp_path: Path):
    assert load_latest_handoff(tmp_path, "nonexistent#1") is None
