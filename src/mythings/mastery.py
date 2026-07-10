from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The learn-loop's shared state, the counterpart to mythings.corpus: corpus is
# the read side (curriculum text in), mastery is the feedback side (what the
# learner has and hasn't mastered out). Consumers append graded Attempts to a
# local JSONL ledger — same append-only discipline as the dev-ledger, and
# deliberately NOT a PR per answer so a cram session stays ceremony-free.


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    unit: str | None = None


@dataclass(frozen=True)
class Attempt:
    topic: str  # Topic.slug
    at: str  # ISO-8601 UTC timestamp
    score: float  # 0.0 (blank) .. 1.0 (perfect)
    kind: str  # "quiz" | "flashcard" | "recall" | "exam"
    gaps: tuple[str, ...] = ()  # short phrases of what was missed
    source: str = ""  # tool that recorded it (my-professor, my-flashcards, ...)


@dataclass(frozen=True)
class Mastery:
    topic: str
    attempts: int
    score: float  # recency-decayed mean, 0.0 .. 1.0
    last_seen: str | None
    next_due: str | None  # when this topic should resurface
    gaps: tuple[str, ...]


def now_iso(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _row(a: Attempt) -> dict[str, object]:
    return {
        "topic": a.topic,
        "at": a.at,
        "score": a.score,
        "kind": a.kind,
        "gaps": list(a.gaps),
        "source": a.source,
    }


def _attempt(row: dict[str, object]) -> Attempt:
    return Attempt(
        topic=str(row["topic"]),
        at=str(row["at"]),
        score=float(row["score"]),
        kind=str(row["kind"]),
        gaps=tuple(str(g) for g in row.get("gaps", ())),
        source=str(row.get("source", "")),
    )


def record(path: str | Path, attempt: Attempt) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row(attempt), ensure_ascii=False) + "\n")


def load(path: str | Path) -> list[Attempt]:
    path = Path(path)
    if not path.exists():
        return []
    out: list[Attempt] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(_attempt(json.loads(line)))
    return out


def schedule(mastery: Mastery, *, base_days: float = 1.0) -> str | None:
    # Spaced repetition: a weak topic (score near 0) comes back immediately;
    # a well-known one earns an interval that grows with both its score and how
    # many times it has been seen. score is squared so the spacing stays short
    # until mastery is genuinely high.
    if mastery.last_seen is None:
        return None
    interval = base_days * (1 + mastery.attempts) * max(mastery.score, 0.0) ** 2
    return now_iso(_parse(mastery.last_seen) + timedelta(days=interval))


def rollup(
    attempts: Iterable[Attempt],
    *,
    half_life_days: float = 7.0,
    now: datetime | None = None,
) -> list[Mastery]:
    now = now or datetime.now(UTC)
    by_topic: dict[str, list[Attempt]] = {}
    for a in attempts:
        by_topic.setdefault(a.topic, []).append(a)

    out: list[Mastery] = []
    for topic, items in by_topic.items():
        items = sorted(items, key=lambda a: a.at)
        num = den = 0.0
        for a in items:
            age_days = max((now - _parse(a.at)).total_seconds() / 86400.0, 0.0)
            weight = 0.5 ** (age_days / half_life_days)
            num += weight * a.score
            den += weight
        score = num / den if den else 0.0
        last = items[-1]
        mastery = Mastery(
            topic=topic,
            attempts=len(items),
            score=score,
            last_seen=last.at,
            next_due=None,
            gaps=last.gaps,
        )
        out.append(_replace_due(mastery))
    return sorted(out, key=lambda m: m.topic)


def _replace_due(mastery: Mastery) -> Mastery:
    return Mastery(
        topic=mastery.topic,
        attempts=mastery.attempts,
        score=mastery.score,
        last_seen=mastery.last_seen,
        next_due=schedule(mastery),
        gaps=mastery.gaps,
    )


def due(
    masteries: Iterable[Mastery],
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Mastery]:
    now = now or datetime.now(UTC)
    ready = [m for m in masteries if m.next_due is None or _parse(m.next_due) <= now]
    # Weakest first, then whatever has waited longest.
    ready.sort(key=lambda m: (m.score, m.next_due or ""))
    return ready[:limit] if limit is not None else ready
