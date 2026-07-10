from datetime import UTC, datetime, timedelta
from pathlib import Path

from mythings.mastery import (
    Attempt,
    Mastery,
    due,
    load,
    now_iso,
    record,
    rollup,
    schedule,
)

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _at(days_ago: float) -> str:
    return now_iso(_NOW - timedelta(days=days_ago))


def test_record_then_load_round_trips(tmp_path: Path) -> None:
    ledger = tmp_path / "mastery.jsonl"
    a = Attempt(topic="em", at=_at(0), score=0.5, kind="quiz", gaps=("Jensen",), source="prof")
    record(ledger, a)
    record(ledger, Attempt(topic="pca", at=_at(1), score=1.0, kind="quiz"))
    loaded = load(ledger)
    assert loaded[0] == a
    assert loaded[1].topic == "pca" and loaded[1].gaps == ()


def test_load_missing_ledger_is_empty(tmp_path: Path) -> None:
    assert load(tmp_path / "nope.jsonl") == []


def test_rollup_recency_decay_favours_recent_scores() -> None:
    attempts = [
        Attempt(topic="em", at=_at(28), score=0.0, kind="quiz"),  # old failure
        Attempt(topic="em", at=_at(0), score=1.0, kind="quiz"),  # fresh success
    ]
    (m,) = rollup(attempts, half_life_days=7.0, now=_NOW)
    assert m.attempts == 2
    # the 28-day-old zero is decayed 4 half-lives (~1/16), so score is well above 0.5
    assert m.score > 0.9


def test_rollup_carries_latest_gaps() -> None:
    attempts = [
        Attempt(topic="em", at=_at(3), score=0.2, kind="quiz", gaps=("old",)),
        Attempt(topic="em", at=_at(1), score=0.4, kind="quiz", gaps=("M-step",)),
    ]
    (m,) = rollup(attempts, now=_NOW)
    assert m.gaps == ("M-step",)


def test_weak_topic_is_due_now_strong_topic_is_spaced() -> None:
    weak = Mastery("em", attempts=1, score=0.0, last_seen=_at(0), next_due=None, gaps=())
    strong = Mastery("pca", attempts=5, score=1.0, last_seen=_at(0), next_due=None, gaps=())
    assert schedule(weak) == weak.last_seen  # interval 0 -> due immediately
    assert datetime.fromisoformat(schedule(strong)) > _NOW  # spaced into the future


def test_due_orders_weakest_first_and_hides_not_yet_due() -> None:
    # Attempts sit a day in the past, so the query at _NOW is a genuine "what
    # should I study now" — a topic just seen this instant is never yet due.
    masteries = rollup(
        [
            Attempt(topic="strong", at=_at(2), score=1.0, kind="quiz"),
            Attempt(topic="strong", at=_at(1), score=1.0, kind="quiz"),
            Attempt(topic="weak", at=_at(1), score=0.1, kind="quiz"),
            Attempt(topic="mid", at=_at(1), score=0.5, kind="quiz"),
        ],
        now=_NOW,
    )
    ordered = due(masteries, now=_NOW)
    topics = [m.topic for m in ordered]
    assert topics[0] == "weak"  # weakest surfaces first
    assert "strong" not in topics  # spaced past _NOW, not yet due
    assert due(masteries, now=_NOW, limit=1)[0].topic == "weak"
