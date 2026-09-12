from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

# The CAD loop's durable memory of *a unit of work and its verdict*. Ledger
# records events as they happen; this records what a task is, what became of
# it, and what the next session needs to know -- the shape a goal spanning
# dozens of sessions has to be resumed, measured and audited from.
#
# Same append-only JSONL discipline as mythings.mastery: a write is one line,
# history is never rewritten, and the current state of a task is the last line
# mentioning it. Nothing here calls an Engine or GitHub; it is data and IO.

# Bound on notes_for_peers. Long enough for "tried X, it deadlocks because Y",
# short enough that a resuming session can read every peer's note. Over-long
# notes are truncated rather than rejected: the writer is usually a model at
# the end of a session, and losing the whole record to a ValueError costs more
# than losing the tail of one sentence.
NOTES_MAX = 500


class TaskState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"


# States this loop will never pick a task up from again: either it is finished
# or it is a human's problem now.
_TERMINAL = (TaskState.DONE, TaskState.REJECTED, TaskState.NEEDS_HUMAN)


class Outcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"


@dataclass(frozen=True)
class Check:
    name: str
    # True passed, False failed on evidence, None could not be evaluated. The
    # three-way is load-bearing: "I looked and it is bad" and "I cannot tell"
    # have opposite follow-ups, and a gate that cannot say "I don't know"
    # eventually says "yes" instead.
    passed: bool | None
    detail: str = ""


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    checks: tuple[Check, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class TaskRecord:
    session_id: str
    task_id: str
    lane: str = ""
    repo: str = ""
    issue: int | None = None
    depends_on: tuple[str, ...] = ()  # other TaskRecord.task_id
    state: TaskState = TaskState.READY
    attempts: int = 0
    budget_usd: float = 0.0
    spent_usd: float = 0.0
    branch: str = ""
    pr: int | None = None
    verdict: Verdict | None = None
    notes_for_peers: str = ""

    def __post_init__(self) -> None:
        if len(self.notes_for_peers) > NOTES_MAX:
            object.__setattr__(self, "notes_for_peers", self.notes_for_peers[: NOTES_MAX - 1] + "…")


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    project: str = ""
    lane: str = ""
    statement: str = ""
    done_when: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    milestone: str | None = None
    opened: str = ""  # ISO-8601 UTC
    expires: str = ""  # ISO-8601 UTC -- a goal with no end date never ends
    session_budget: int = 0
    usd_budget: float = 0.0
    sessions_used: int = 0
    state: str = "open"


@dataclass(frozen=True)
class GoalJournalEntry:
    session_id: str
    ts: str  # ISO-8601 UTC
    goal_id: str = ""
    accepted: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    # The only channel carrying knowledge nothing else holds: everything else
    # about a task is recoverable from GitHub, "we tried X and it does not
    # work, because Y" is recoverable from nowhere.
    dead_ends: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    spent_usd: float = 0.0


Record = TaskRecord | GoalRecord | GoalJournalEntry


# Raised when a line that is *not* the store's last fails to parse -- see load().
class CorruptStore(Exception):
    pass


def now_iso(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def _verdict_row(v: Verdict) -> dict[str, object]:
    return {
        "outcome": str(v.outcome),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in v.checks],
        "reason": v.reason,
    }


def _verdict(row: dict[str, object] | None) -> Verdict | None:
    if row is None:
        return None
    checks = row.get("checks") or []
    return Verdict(
        outcome=Outcome(str(row["outcome"])),
        checks=tuple(
            Check(name=str(c["name"]), passed=c["passed"], detail=str(c.get("detail", "")))
            for c in checks
        ),
        reason=str(row.get("reason", "")),
    )


def _row(rec: Record) -> dict[str, object]:
    if isinstance(rec, TaskRecord):
        return {
            "record": "task",
            "session_id": rec.session_id,
            "task_id": rec.task_id,
            "lane": rec.lane,
            "repo": rec.repo,
            "issue": rec.issue,
            "depends_on": list(rec.depends_on),
            "state": str(rec.state),
            "attempts": rec.attempts,
            "budget_usd": rec.budget_usd,
            "spent_usd": rec.spent_usd,
            "branch": rec.branch,
            "pr": rec.pr,
            "verdict": _verdict_row(rec.verdict) if rec.verdict else None,
            "notes_for_peers": rec.notes_for_peers,
        }
    if isinstance(rec, GoalRecord):
        return {
            "record": "goal",
            "goal_id": rec.goal_id,
            "project": rec.project,
            "lane": rec.lane,
            "statement": rec.statement,
            "done_when": list(rec.done_when),
            "phases": list(rec.phases),
            "milestone": rec.milestone,
            "opened": rec.opened,
            "expires": rec.expires,
            "session_budget": rec.session_budget,
            "usd_budget": rec.usd_budget,
            "sessions_used": rec.sessions_used,
            "state": rec.state,
        }
    return {
        "record": "journal",
        "session_id": rec.session_id,
        "ts": rec.ts,
        "goal_id": rec.goal_id,
        "accepted": list(rec.accepted),
        "rejected": list(rec.rejected),
        "dead_ends": list(rec.dead_ends),
        "decisions": list(rec.decisions),
        "spent_usd": rec.spent_usd,
    }


def _strs(row: dict[str, object], key: str) -> tuple[str, ...]:
    values = row.get(key) or ()
    return tuple(str(v) for v in values)  # type: ignore[union-attr]


def _record(row: dict[str, object]) -> Record:
    kind = row.get("record")
    if kind == "task":
        issue, pr = row.get("issue"), row.get("pr")
        verdict = row.get("verdict")
        return TaskRecord(
            session_id=str(row["session_id"]),
            task_id=str(row["task_id"]),
            lane=str(row.get("lane", "")),
            repo=str(row.get("repo", "")),
            issue=int(issue) if issue is not None else None,  # type: ignore[arg-type]
            depends_on=_strs(row, "depends_on"),
            state=TaskState(str(row.get("state", TaskState.READY))),
            attempts=int(row.get("attempts", 0)),  # type: ignore[arg-type]
            budget_usd=float(row.get("budget_usd", 0.0)),  # type: ignore[arg-type]
            spent_usd=float(row.get("spent_usd", 0.0)),  # type: ignore[arg-type]
            branch=str(row.get("branch", "")),
            pr=int(pr) if pr is not None else None,  # type: ignore[arg-type]
            verdict=_verdict(verdict),  # type: ignore[arg-type]
            notes_for_peers=str(row.get("notes_for_peers", "")),
        )
    if kind == "goal":
        milestone = row.get("milestone")
        return GoalRecord(
            goal_id=str(row["goal_id"]),
            project=str(row.get("project", "")),
            lane=str(row.get("lane", "")),
            statement=str(row.get("statement", "")),
            done_when=_strs(row, "done_when"),
            phases=_strs(row, "phases"),
            milestone=str(milestone) if milestone is not None else None,
            opened=str(row.get("opened", "")),
            expires=str(row.get("expires", "")),
            session_budget=int(row.get("session_budget", 0)),  # type: ignore[arg-type]
            usd_budget=float(row.get("usd_budget", 0.0)),  # type: ignore[arg-type]
            sessions_used=int(row.get("sessions_used", 0)),  # type: ignore[arg-type]
            state=str(row.get("state", "open")),
        )
    if kind == "journal":
        return GoalJournalEntry(
            session_id=str(row["session_id"]),
            ts=str(row["ts"]),
            goal_id=str(row.get("goal_id", "")),
            accepted=_strs(row, "accepted"),
            rejected=_strs(row, "rejected"),
            dead_ends=_strs(row, "dead_ends"),
            decisions=_strs(row, "decisions"),
            spent_usd=float(row.get("spent_usd", 0.0)),  # type: ignore[arg-type]
        )
    raise ValueError(f"unknown record kind: {kind!r}")


def record(path: str | Path, rec: Record) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row(rec), ensure_ascii=False) + "\n")


def load(path: str | Path) -> list[Record]:
    path = Path(path)
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: list[Record] = []
    for i, line in enumerate(lines):
        try:
            out.append(_record(json.loads(line)))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # A torn *last* line is the expected failure of an append-only file
            # whose writer was killed mid-write: drop it, keep the history. A
            # bad line anywhere else means the file was rewritten or two
            # writers interleaved, which is not something to paper over.
            if i == len(lines) - 1:
                break
            raise CorruptStore(f"{path}: line {i + 1} did not parse") from exc
    return out


def tasks(records: Iterable[Record]) -> list[TaskRecord]:
    # Append-only: a task's current state is its last line. Dict insertion
    # order keeps the list in first-seen order as tasks are updated.
    latest: dict[str, TaskRecord] = {}
    for r in records:
        if isinstance(r, TaskRecord):
            latest[r.task_id] = r
    return list(latest.values())


def goals(records: Iterable[Record]) -> list[GoalRecord]:
    latest: dict[str, GoalRecord] = {}
    for r in records:
        if isinstance(r, GoalRecord):
            latest[r.goal_id] = r
    return list(latest.values())


def journal(records: Iterable[Record]) -> list[GoalJournalEntry]:
    # Journal entries are events, not state, so every one of them is kept.
    return [r for r in records if isinstance(r, GoalJournalEntry)]


_MISSING = TaskRecord(session_id="", task_id="", state=TaskState.BLOCKED)


def ready(items: Iterable[TaskRecord]) -> list[TaskRecord]:
    items = list(items)
    by_id = {t.task_id: t for t in items}
    out = []
    for t in items:
        if t.state in _TERMINAL or t.state == TaskState.RUNNING:
            continue
        # A dependency id with no matching task (typo/dangling edge) counts as
        # unmet -- fail closed, never assume a missing task is done.
        if all(by_id.get(dep, _MISSING).state == TaskState.DONE for dep in t.depends_on):
            out.append(t)
    return out


def running(items: Iterable[TaskRecord]) -> list[TaskRecord]:
    # The resume path: rows still marked running when a store is reopened were
    # interrupted, and are what a recovering session has to reconcile first.
    return [t for t in items if t.state == TaskState.RUNNING]
