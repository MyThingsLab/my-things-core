from __future__ import annotations

import json
from pathlib import Path

import pytest

from mythings.session import (
    NOTES_MAX,
    Check,
    CorruptStore,
    GoalJournalEntry,
    GoalRecord,
    Outcome,
    TaskRecord,
    TaskState,
    Verdict,
    goals,
    journal,
    load,
    now_iso,
    ready,
    record,
    running,
    tasks,
)


def _task(task_id: str, **kw: object) -> TaskRecord:
    return TaskRecord(session_id="s1", task_id=task_id, **kw)  # type: ignore[arg-type]


def test_task_record_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    rec = TaskRecord(
        session_id="s1",
        task_id="t1",
        lane="kernel",
        repo="my-things-core",
        issue=148,
        depends_on=("t0",),
        state=TaskState.RUNNING,
        attempts=2,
        budget_usd=5.0,
        spent_usd=1.25,
        branch="feat/session-records",
        pr=156,
        verdict=Verdict(
            outcome=Outcome.NEEDS_HUMAN,
            checks=(
                Check("not_draft", True, "ready for review"),
                Check("required_checks_pass", None, "no required checks configured"),
            ),
            reason="required_checks_pass: no required checks configured",
        ),
        notes_for_peers="corpus adoption needs core@main first",
    )
    record(path, rec)

    assert load(path) == [rec]


def test_goal_record_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    rec = GoalRecord(
        goal_id="cad-foundation",
        project="MyThingsLab",
        lane="kernel",
        statement="the CAD loop runs a week unattended",
        done_when=("a goal resumes across sessions", "the gate rejects on evidence"),
        phases=("records", "gate", "loop"),
        milestone="goal/cad-foundation",
        opened="2026-09-12T00:00:00+00:00",
        expires="2026-10-12T00:00:00+00:00",
        session_budget=30,
        usd_budget=200.0,
        sessions_used=3,
        state="open",
    )
    record(path, rec)

    assert load(path) == [rec]


def test_journal_entry_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    rec = GoalJournalEntry(
        session_id="s1",
        ts=now_iso(),
        goal_id="cad-foundation",
        accepted=("t1",),
        rejected=("t2",),
        dead_ends=("a worktree import resolves against main, so the suite tests the wrong tree",),
        decisions=("skipped checks count as unevaluable, not as pass",),
        spent_usd=2.5,
    )
    record(path, rec)

    assert load(path) == [rec]


def test_store_is_append_only_and_mixes_record_types(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    goal = GoalRecord(goal_id="g1", statement="ship the loop")
    task = _task("t1")
    entry = GoalJournalEntry(session_id="s1", ts=now_iso(), goal_id="g1")
    for rec in (goal, task, entry):
        record(path, rec)

    records = load(path)
    assert records == [goal, task, entry]
    assert goals(records) == [goal]
    assert tasks(records) == [task]
    assert journal(records) == [entry]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_latest_line_wins_for_a_task(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1", state=TaskState.RUNNING))
    record(path, _task("t1", state=TaskState.DONE, pr=7))

    current = tasks(load(path))
    assert len(current) == 1
    assert current[0].state == TaskState.DONE
    assert current[0].pr == 7


def test_journal_entries_are_never_collapsed(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, GoalJournalEntry(session_id="s1", ts="2026-09-12T00:00:00+00:00", goal_id="g1"))
    record(path, GoalJournalEntry(session_id="s1", ts="2026-09-12T01:00:00+00:00", goal_id="g1"))

    assert len(journal(load(path))) == 2


def test_load_missing_store_is_empty(tmp_path: Path) -> None:
    assert load(tmp_path / "nope.jsonl") == []


def test_ready_requires_every_dependency_done() -> None:
    done = _task("t0", state=TaskState.DONE)
    blocked = _task("t1", depends_on=("t0", "t2"), state=TaskState.BLOCKED)
    other = _task("t2", state=TaskState.READY)

    assert [t.task_id for t in ready([done, blocked, other])] == ["t2"]

    other_done = _task("t2", state=TaskState.DONE)
    assert [t.task_id for t in ready([done, blocked, other_done])] == ["t1"]


def test_ready_treats_a_dangling_dependency_as_unmet() -> None:
    assert ready([_task("t1", depends_on=("ghost",))]) == []


def test_ready_skips_running_and_terminal_tasks() -> None:
    items = [
        _task("t1", state=TaskState.RUNNING),
        _task("t2", state=TaskState.DONE),
        _task("t3", state=TaskState.REJECTED),
        _task("t4", state=TaskState.NEEDS_HUMAN),
        _task("t5", state=TaskState.READY),
    ]
    assert [t.task_id for t in ready(items)] == ["t5"]


def test_running_rows_survive_a_reopen_for_recovery(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1", state=TaskState.RUNNING, attempts=1, branch="feat/x"))
    record(path, _task("t2", state=TaskState.DONE))

    resumed = running(tasks(load(path)))
    assert [t.task_id for t in resumed] == ["t1"]
    assert resumed[0].branch == "feat/x"


def test_a_task_that_finished_is_no_longer_running(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1", state=TaskState.RUNNING))
    record(path, _task("t1", state=TaskState.DONE))

    assert running(tasks(load(path))) == []


def test_truncated_final_line_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"record": "task", "session_id": "s1", "task_i')  # killed mid-write

    records = load(path)
    assert [r.task_id for r in tasks(records)] == ["t1"]


def test_final_line_missing_a_required_field_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "task", "session_id": "s1"}) + "\n")

    assert [r.task_id for r in tasks(load(path))] == ["t1"]


def test_corrupt_interior_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record(path, _task("t1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    record(path, _task("t2"))

    with pytest.raises(CorruptStore, match="line 2"):
        load(path)


def test_unknown_record_kind_in_an_interior_line_raises(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "wat"}) + "\n")
    record(path, _task("t1"))

    with pytest.raises(CorruptStore, match="line 1"):
        load(path)


def test_notes_for_peers_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    rec = _task("t1", notes_for_peers="x" * (NOTES_MAX + 200))
    assert len(rec.notes_for_peers) == NOTES_MAX
    assert rec.notes_for_peers.endswith("…")

    record(path, rec)
    assert load(path) == [rec]


def test_a_goal_survives_the_session_that_opened_it(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    for rec in (
        GoalRecord(goal_id="g1", statement="ship the loop", session_budget=30, sessions_used=1),
        _task("t0", state=TaskState.DONE),
        _task("t1", depends_on=("t0",), state=TaskState.RUNNING),
        GoalJournalEntry(session_id="s1", ts=now_iso(), goal_id="g1", accepted=("t0",)),
    ):
        record(path, rec)

    # A later session reopens the same store and picks up where s1 stopped.
    reopened = load(path)
    assert [g.sessions_used for g in goals(reopened)] == [1]
    assert [t.task_id for t in running(tasks(reopened))] == ["t1"]
    assert [e.accepted for e in journal(reopened)] == [("t0",)]

    record(path, _task("t1", state=TaskState.DONE))
    record(path, _task("t2", depends_on=("t1",)))
    final = tasks(load(path))
    assert running(final) == []
    assert [t.task_id for t in ready(final)] == ["t2"]
