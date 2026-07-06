from pathlib import Path

from mythings.ledger import Ledger, LedgerEntry


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
