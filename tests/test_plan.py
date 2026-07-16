import json

from mythings.plan import PlanTask, parse, ready, reconcile, render
from mythings.testing import FakeGh

_TABLE = """\
| Task | Owner | Depends on | Issue | Status |
|---|---|---|---|---|
| add STAT_DIM guard | data | | #42 | done |
| wire graph consumer | features | add STAT_DIM guard | #57 | todo |
| dangling dep | features | no such task | | todo |
"""


def test_parse_reads_title_owner_deps_issue_status() -> None:
    tasks = parse(_TABLE)

    assert tasks == [
        PlanTask(title="add STAT_DIM guard", owner="data", issue=42, status="done"),
        PlanTask(
            title="wire graph consumer",
            owner="features",
            depends_on=("add STAT_DIM guard",),
            issue=57,
            status="todo",
        ),
        PlanTask(title="dangling dep", owner="features", depends_on=("no such task",)),
    ]


def test_render_round_trips_through_parse() -> None:
    tasks = parse(_TABLE)

    assert parse(render(tasks)) == tasks


def test_parse_ignores_prose_outside_the_table() -> None:
    text = "# Plan: example\n\nSome narrative context.\n\n" + _TABLE + "\nMore prose.\n"

    assert parse(text) == parse(_TABLE)


def test_ready_excludes_done_tasks_and_surfaces_satisfied_ones() -> None:
    tasks = parse(_TABLE)

    out = ready(tasks)

    titles = {t.title for t in out}
    assert "add STAT_DIM guard" not in titles  # already done, not a candidate
    assert "wire graph consumer" in titles  # its one dependency is already done


def test_ready_excludes_task_with_undone_dependency() -> None:
    tasks = [
        PlanTask(title="a", owner="x", status="todo"),
        PlanTask(title="b", owner="x", depends_on=("a",), status="todo"),
    ]

    out = ready(tasks)

    assert [t.title for t in out] == ["a"]  # "b" is blocked until "a" is done


def test_ready_treats_dangling_dependency_as_not_ready() -> None:
    tasks = parse(_TABLE)

    out = ready(tasks)

    assert "dangling dep" not in {t.title for t in out}


def test_ready_surfaces_a_task_whose_dependency_is_done() -> None:
    tasks = [
        PlanTask(title="a", owner="x", status="done"),
        PlanTask(title="b", owner="x", depends_on=("a",), status="todo"),
    ]

    out = ready(tasks)

    assert [t.title for t in out] == ["b"]


def test_reconcile_marks_closed_issue_done() -> None:
    tasks = [PlanTask(title="t", owner="x", issue=1, status="todo")]
    runner = FakeGh(
        {
            ("issue", "view"): "CLOSED",
            ("pr", "list"): json.dumps([]),
        }
    )

    out, changed = reconcile(tasks, repo="MyThingsLab/x", runner=runner)

    assert changed is True
    assert out[0].status == "done"


def test_reconcile_marks_in_progress_on_open_pr_reference() -> None:
    tasks = [PlanTask(title="t", owner="x", issue=1, status="todo")]
    runner = FakeGh(
        {
            ("issue", "view"): "OPEN",
            ("pr", "list"): json.dumps([{"number": 9}]),
        }
    )

    out, changed = reconcile(tasks, repo="MyThingsLab/x", runner=runner)

    assert changed is True
    assert out[0].status == "in_progress"


def test_reconcile_leaves_task_unchanged_with_no_signal() -> None:
    tasks = [PlanTask(title="t", owner="x", issue=1, status="todo")]
    runner = FakeGh(
        {
            ("issue", "view"): "OPEN",
            ("pr", "list"): json.dumps([]),
        }
    )

    out, changed = reconcile(tasks, repo="MyThingsLab/x", runner=runner)

    assert changed is False
    assert out[0].status == "todo"


def test_reconcile_skips_tasks_with_no_issue_or_already_done() -> None:
    tasks = [
        PlanTask(title="no issue", owner="x", status="todo"),
        PlanTask(title="already done", owner="x", issue=2, status="done"),
    ]
    runner = FakeGh({})  # any call would be an unexpected-call failure

    out, changed = reconcile(tasks, repo="MyThingsLab/x", runner=runner)

    assert changed is False
    assert out == tasks
