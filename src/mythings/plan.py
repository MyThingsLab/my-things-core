from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mythings.github import Runner, _gh

_STATUSES = ("todo", "in_progress", "done")

# A plan's tasks reference each other by title in "Depends on" -- no separate
# id column, matching how the source system (a real product repo's own plan
# tables) writes them. Titles must be unique within one plan file.
_ROW = re.compile(r"^\|(.+)\|\s*$")
_MILESTONE_HEADER = re.compile(r"^#?\s*(?:Goal|Milestone):\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class PlanTask:
    title: str
    owner: str
    depends_on: tuple[str, ...] = ()
    issue: int | None = None
    status: str = "todo"


@dataclass(frozen=True)
class Plan:
    tasks: tuple[PlanTask, ...] = ()
    milestone: str | None = None


def parse_plan(text: str) -> Plan:
    milestone: str | None = None
    for line in text.splitlines():
        if m := _MILESTONE_HEADER.match(line.strip()):
            milestone = m.group(1).strip()
            break

    rows = [m.group(1) for line in text.splitlines() if (m := _ROW.match(line))]
    tasks = []
    for row in rows[2:]:  # skip the header row and the "|---|...|" separator row
        cells = [c.strip() for c in row.split("|")]
        if len(cells) < 5:
            continue
        title, owner, deps, issue_cell, status_cell = cells[:5]
        if not title:
            continue
        depends_on = tuple(d.strip() for d in deps.split(",") if d.strip())
        issue = int(issue_cell.lstrip("#")) if issue_cell.lstrip("#").isdigit() else None
        status = status_cell if status_cell in _STATUSES else "todo"
        tasks.append(
            PlanTask(title=title, owner=owner, depends_on=depends_on, issue=issue, status=status)
        )
    return Plan(tasks=tuple(tasks), milestone=milestone)


def parse(text: str) -> list[PlanTask]:
    return list(parse_plan(text).tasks)


def render(tasks: list[PlanTask] | Plan, *, milestone: str | None = None) -> str:
    if isinstance(tasks, Plan):
        milestone = tasks.milestone if milestone is None else milestone
        task_list = list(tasks.tasks)
    else:
        task_list = tasks

    lines = []
    if milestone:
        lines.append(f"# Goal: {milestone}\n")

    lines.extend(["| Task | Owner | Depends on | Issue | Status |", "|---|---|---|---|---|"])
    for t in task_list:
        deps = ", ".join(t.depends_on)
        issue = f"#{t.issue}" if t.issue is not None else ""
        lines.append(f"| {t.title} | {t.owner} | {deps} | {issue} | {t.status} |")
    return "\n".join(lines) + "\n"


def read_plan(path: str | Path) -> list[PlanTask]:
    return parse(Path(path).read_text(encoding="utf-8"))


def read_plan_object(path: str | Path) -> Plan:
    return parse_plan(Path(path).read_text(encoding="utf-8"))


def write_plan(
    path: str | Path, tasks: list[PlanTask] | Plan, *, milestone: str | None = None
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(tasks, milestone=milestone), encoding="utf-8")


_MISSING = PlanTask(title="", owner="", status="todo")


def ready(tasks: list[PlanTask] | Plan) -> list[PlanTask]:
    task_list = list(tasks.tasks) if isinstance(tasks, Plan) else tasks
    by_title = {t.title: t for t in task_list}
    out = []
    for t in task_list:
        if t.status == "done":
            continue
        # A dependency title with no matching task (typo/dangling edge) is
        # treated as unmet -- fail closed, never assume a missing task is done.
        if all(by_title.get(dep, _MISSING).status == "done" for dep in t.depends_on):
            out.append(t)
    return out


def reconcile_plan(
    plan: Plan,
    *,
    repo: str,
    runner: Runner = _gh,
) -> tuple[Plan, bool, tuple[int, ...]]:
    milestone_drift: list[int] = []
    changed = False
    out = []
    for t in plan.tasks:
        if t.issue is None:
            out.append(t)
            continue

        if plan.milestone is not None:
            issue_m = _issue_milestone(repo, t.issue, runner)
            if issue_m != plan.milestone:
                milestone_drift.append(t.issue)

        if t.status == "done":
            out.append(t)
            continue

        new_status = t.status
        if _issue_state(repo, t.issue, runner) == "CLOSED":
            new_status = "done"
        elif _open_pr_references(repo, t.issue, runner):
            new_status = "in_progress"

        if new_status != t.status:
            changed = True
            out.append(
                PlanTask(
                    title=t.title,
                    owner=t.owner,
                    depends_on=t.depends_on,
                    issue=t.issue,
                    status=new_status,
                )
            )
        else:
            out.append(t)

    new_plan = Plan(tasks=tuple(out), milestone=plan.milestone)
    return new_plan, changed, tuple(milestone_drift)


def reconcile(
    tasks: list[PlanTask] | Plan,
    *,
    repo: str,
    runner: Runner = _gh,
    milestone: str | None = None,
) -> tuple[list[PlanTask], bool]:
    if isinstance(tasks, Plan):
        plan = tasks if milestone is None else Plan(tasks=tasks.tasks, milestone=milestone)
    else:
        plan = Plan(tasks=tuple(tasks), milestone=milestone)

    new_plan, changed, _ = reconcile_plan(plan, repo=repo, runner=runner)
    return list(new_plan.tasks), changed


def _issue_state(repo: str, number: int, runner: Runner) -> str:
    argv = ["issue", "view", str(number), "--repo", repo, "--json", "state", "-q", ".state"]
    return runner(argv).strip()


def _issue_milestone(repo: str, number: int, runner: Runner) -> str | None:
    argv = [
        "issue",
        "view",
        str(number),
        "--repo",
        repo,
        "--json",
        "milestone",
        "-q",
        ".milestone.title",
    ]
    raw = runner(argv).strip()
    return raw if raw and raw != "null" else None


def _open_pr_references(repo: str, number: int, runner: Runner) -> bool:
    # Text search, not GitHub's structured "closing issue" graph -- can
    # false-positive on a PR that merely mentions the number. Acceptable
    # first cut (mirrors the source system's own reconcile); a GraphQL
    # cross-reference query (see projects.py's _graphql pattern) is a
    # follow-up once a real consumer shows this matters.
    argv = [
        "pr", "list", "--repo", repo, "--state", "open",
        "--search", f"{number} in:body", "--json", "number",
    ]
    return bool(json.loads(runner(argv)))
