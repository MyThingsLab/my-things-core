from pathlib import Path

from mythings.ledger import Ledger, LedgerEntry, render_resume_pack


def test_append_is_additive_and_roundtrips(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "run.jsonl")
    led.record("my-guard", "policy", "deny", detail="git push on main", rule="protect_main")
    led.record("my-tester", "run", "success")

    entries = list(led)
    assert len(entries) == 2
    assert entries[0].tool == "my-guard"
    assert entries[0].data["rule"] == "protect_main"
    assert entries[1].outcome == "success"


def test_read_filters_by_tool_and_kind(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "run.jsonl")
    led.record("my-guard", "policy", "allow")
    led.record("my-guard", "run", "success")
    led.record("my-tester", "policy", "ask")

    assert len(led.read(tool="my-guard")) == 2
    assert len(led.read(kind="policy")) == 2
    assert len(led.read(tool="my-guard", kind="policy")) == 1


def test_entry_json_roundtrip() -> None:
    e = LedgerEntry(tool="t", kind="k", outcome="o", detail="d", data={"n": 1})
    assert LedgerEntry.from_json(e.to_json()) == e


def test_iter_on_missing_file_is_empty(tmp_path: Path) -> None:
    assert list(Ledger(tmp_path / "absent.jsonl")) == []


def test_append_creates_parent_dirs(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "nested" / "deep" / "run.jsonl")
    led.record("t", "k", "o")
    assert led.path.exists()


def test_token_tracking_properties() -> None:
    e = LedgerEntry(
        tool="my-coder",
        kind="dispatch",
        outcome="ok",
        data={"prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.05},
    )
    assert e.prompt_tokens == 1000
    assert e.completion_tokens == 200
    assert e.total_tokens == 1200
    assert e.cost_usd == 0.05


def test_get_checkpoint(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "run.jsonl")
    led.record(
        "fleet_dispatch",
        "dispatch",
        "failed",
        detail="test broken_func failed",
        candidate="my-tool#1",
        target_symbols=["symbol:broken_func"],
        failed_tests=["tests/test_core.py::test_broken"],
        prompt_tokens=500,
        completion_tokens=100,
        cost_usd=0.02,
    )
    led.record(
        "fleet_dispatch",
        "dispatch",
        "needs_human",
        detail="capability missing",
        candidate="my-tool#1",
        prompt_tokens=300,
        completion_tokens=50,
        cost_usd=0.01,
    )

    cp = led.get_checkpoint("my-tool#1")
    assert cp is not None
    assert cp.candidate_id == "my-tool#1"
    assert cp.last_outcome == "needs_human"
    assert cp.attempt_count == 2
    assert cp.total_tokens == 950
    assert cp.target_symbols == ["symbol:broken_func"]
    assert cp.failed_tests == ["tests/test_core.py::test_broken"]
    assert cp.blocker_reason == "capability missing"

    pack = render_resume_pack(cp)
    assert "Prior Attempt Checkpoint" in pack
    assert "symbol:broken_func" in pack
    assert "capability missing" in pack
