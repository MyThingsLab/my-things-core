from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mythings.contract import (
    CriterionKind,
    already_green,
    grade,
    parse_criteria,
    parse_criterion,
    run_criteria,
)
from mythings.policy import ALLOW, Action, Decision, PolicyResult
from mythings.session import Check, Outcome


class _DenyPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return PolicyResult(Decision.DENY, reason="not here", rule="test")


class _AskPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return PolicyResult(Decision.ASK, reason="confirm first", rule="test")


class _AllowPolicy:
    def __init__(self) -> None:
        self.seen: list[Action] = []

    def evaluate(self, action: Action) -> PolicyResult:
        self.seen.append(action)
        return ALLOW


def _runner(replies: dict[str, str]):
    def run(argv: list[str]) -> str:
        return replies[argv[0]]

    return run


# ---- parsing --------------------------------------------------------------


def test_command_criterion_is_split_argv_only() -> None:
    crit = parse_criterion("$ pytest tests/test_heartbeat.py::test_alerts")
    assert crit.kind is CriterionKind.COMMAND
    assert crit.argv == ("pytest", "tests/test_heartbeat.py::test_alerts")
    assert crit.executable


def test_quoted_command_argument_survives_splitting() -> None:
    crit = parse_criterion('$ pytest -k "alerts when stale"')
    assert crit.argv == ("pytest", "-k", "alerts when stale")


@pytest.mark.parametrize(
    "line",
    [
        "$ pytest foo | grep -q PASS",
        "$ rm -rf / ; echo done",
        "$ cat x > y",
        "$ pytest && rm -rf .git",
    ],
)
def test_bare_shell_operators_degrade_to_prose(line: str) -> None:
    # The security property: a milestone description is an editable GitHub
    # field, so a pipeline must never reach a shell.
    crit = parse_criterion(line)
    assert crit.kind is CriterionKind.PROSE
    assert not crit.executable
    assert crit.note


def test_semicolon_inside_a_quoted_argument_is_still_executable() -> None:
    # Post-split, the semicolon lives inside one argv element, so there is no
    # shell to interpret it -- rejecting this would block every `python -c`.
    crit = parse_criterion('$ python -c "import sys; sys.exit(0)"')
    assert crit.kind is CriterionKind.COMMAND
    assert crit.argv == ("python", "-c", "import sys; sys.exit(0)")


def test_command_substitution_is_passed_through_as_a_literal() -> None:
    # Harmless with shell=False: it becomes the literal string "$(whoami)",
    # never an executed subshell.
    crit = parse_criterion("$ echo $(whoami)")
    assert crit.argv == ("echo", "$(whoami)")


def test_unbalanced_quote_degrades_to_prose_with_a_reason() -> None:
    crit = parse_criterion('$ pytest -k "unclosed')
    assert crit.kind is CriterionKind.PROSE
    assert "unparsable" in crit.note


def test_structured_github_criteria_parse() -> None:
    ci = parse_criterion("ci_green MyThingsLab/my-fleet")
    assert (ci.kind, ci.repo) == (CriterionKind.CI_GREEN, "MyThingsLab/my-fleet")

    pr = parse_criterion("pr_merged MyThingsLab/my-fleet#101")
    assert (pr.kind, pr.repo, pr.number) == (CriterionKind.PR_MERGED, "MyThingsLab/my-fleet", 101)

    issue = parse_criterion("issue_closed MyThingsLab/my-fleet#27")
    assert (issue.kind, issue.number) == (CriterionKind.ISSUE_CLOSED, 27)


@pytest.mark.parametrize(
    "line",
    ["pr_merged MyThingsLab/my-fleet", "issue_closed #12", "pr_merged repo#notanumber"],
)
def test_malformed_refs_degrade_to_prose(line: str) -> None:
    assert parse_criterion(line).kind is CriterionKind.PROSE


def test_plain_english_stays_prose() -> None:
    crit = parse_criterion("the operator sees the failure on their phone within 10 minutes")
    assert crit.kind is CriterionKind.PROSE
    assert not crit.executable


def test_parse_criteria_preserves_order_and_mixes_kinds() -> None:
    crits = parse_criteria(["$ true", "ci_green a/b", "a human reads it"])
    assert [c.kind for c in crits] == [
        CriterionKind.COMMAND,
        CriterionKind.CI_GREEN,
        CriterionKind.PROSE,
    ]


def test_criterion_name_is_stable_across_runs() -> None:
    assert parse_criterion("$ true").name == parse_criterion("$ true").name


# ---- execution ------------------------------------------------------------


def test_passing_and_failing_commands_report_real_exit_codes(tmp_path: Path) -> None:
    crits = parse_criteria([f"$ {sys.executable} -c pass", f"$ {sys.executable} -c exit(3)"])
    checks = run_criteria(crits, cwd=tmp_path)
    assert [c.passed for c in checks] == [True, False]
    assert "exit 0" in checks[0].detail
    assert "exit 3" in checks[1].detail


def test_missing_binary_is_unevaluable_not_failed(tmp_path: Path) -> None:
    # None, not False: "could not run" must not read as "ran and failed".
    (check,) = run_criteria(parse_criteria(["$ definitely-not-a-real-binary-xyz"]), cwd=tmp_path)
    assert check.passed is None
    assert "not found" in check.detail


def test_timeout_is_unevaluable(tmp_path: Path) -> None:
    crits = parse_criteria([f'$ {sys.executable} -c "import time; time.sleep(30)"'])
    (check,) = run_criteria(crits, cwd=tmp_path, timeout=1)
    assert check.passed is None
    assert "timed out" in check.detail


def test_command_runs_in_the_given_directory(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x")
    script = "import pathlib,sys; sys.exit(0 if pathlib.Path('marker.txt').exists() else 1)"
    (check,) = run_criteria(parse_criteria([f"$ {sys.executable} -c {script!r}"]), cwd=tmp_path)
    assert check.passed is True


def test_prose_criterion_is_never_executed(tmp_path: Path) -> None:
    (check,) = run_criteria(parse_criteria(["a human must look at this"]), cwd=tmp_path)
    assert check.passed is None
    assert "human" in check.detail


def test_policy_denial_blocks_execution(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    script = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')"
    crits = parse_criteria([f"$ {sys.executable} -c {script!r}"])
    (check,) = run_criteria(crits, cwd=tmp_path, policy=_DenyPolicy())
    assert check.passed is None
    assert "deny" in check.detail
    assert not marker.exists()


@pytest.mark.parametrize("unattended", [True, False])
def test_core_never_resolves_an_ask_itself(unattended: bool, tmp_path: Path) -> None:
    # Core holds no ask channel (that is myguard's), so an ASK must report
    # unevaluable either way. Running it here would bypass the fleet's human
    # gate -- the caller resolves the ASK and passes the answer back in.
    crits = parse_criteria([f"$ {sys.executable} -c pass"])
    (check,) = run_criteria(crits, cwd=tmp_path, policy=_AskPolicy(), unattended=unattended)
    assert check.passed is None
    expected = "deny" if unattended else "ask"
    assert expected in check.detail


def test_policy_sees_the_argv_it_is_gating(tmp_path: Path) -> None:
    policy = _AllowPolicy()
    run_criteria(parse_criteria([f"$ {sys.executable} -c pass"]), cwd=tmp_path, policy=policy)
    assert policy.seen[0].kind == "run-check"
    assert policy.seen[0].payload["argv"][0] == sys.executable


def test_github_criteria_without_a_runner_are_unevaluable(tmp_path: Path) -> None:
    (check,) = run_criteria(parse_criteria(["ci_green a/b"]), cwd=tmp_path)
    assert check.passed is None
    assert "runner" in check.detail


def test_ci_green_reads_the_latest_main_run(tmp_path: Path) -> None:
    runner = _runner({"run": json.dumps([{"conclusion": "success"}])})
    (check,) = run_criteria(parse_criteria(["ci_green a/b"]), cwd=tmp_path, runner=runner)
    assert check.passed is True

    runner = _runner({"run": json.dumps([{"conclusion": "failure"}])})
    (check,) = run_criteria(parse_criteria(["ci_green a/b"]), cwd=tmp_path, runner=runner)
    assert check.passed is False


def test_ci_run_still_in_progress_is_unevaluable(tmp_path: Path) -> None:
    runner = _runner({"run": json.dumps([{"conclusion": None}])})
    (check,) = run_criteria(parse_criteria(["ci_green a/b"]), cwd=tmp_path, runner=runner)
    assert check.passed is None
    assert "in progress" in check.detail


def test_pr_and_issue_state_checks(tmp_path: Path) -> None:
    runner = _runner({"pr": json.dumps({"state": "MERGED"})})
    (check,) = run_criteria(parse_criteria(["pr_merged a/b#1"]), cwd=tmp_path, runner=runner)
    assert check.passed is True

    runner = _runner({"pr": json.dumps({"state": "OPEN"})})
    (check,) = run_criteria(parse_criteria(["pr_merged a/b#1"]), cwd=tmp_path, runner=runner)
    assert check.passed is False

    runner = _runner({"issue": json.dumps({"state": "CLOSED"})})
    (check,) = run_criteria(parse_criteria(["issue_closed a/b#1"]), cwd=tmp_path, runner=runner)
    assert check.passed is True


def test_github_failure_is_unevaluable_not_failed(tmp_path: Path) -> None:
    def boom(argv: list[str]) -> str:
        raise OSError("gh exploded")

    (check,) = run_criteria(parse_criteria(["ci_green a/b"]), cwd=tmp_path, runner=boom)
    assert check.passed is None
    assert "github lookup failed" in check.detail


# ---- red-first and grading ------------------------------------------------


def test_already_green_names_the_criteria_that_prove_nothing() -> None:
    checks = [Check("a", True), Check("b", False), Check("c", None)]
    assert already_green(checks) == ("a",)


def test_red_to_green_is_accepted() -> None:
    verdict = grade([Check("a", False)], [Check("a", True)])
    assert verdict.outcome is Outcome.ACCEPTED
    assert verdict.checks[0].passed is True
    assert "red at open, green at close" in verdict.checks[0].detail


def test_green_at_open_can_never_be_accepted() -> None:
    # The whole point: a criterion that already passed proves nothing about
    # the work that followed.
    verdict = grade([Check("a", True)], [Check("a", True)])
    assert verdict.outcome is Outcome.NEEDS_HUMAN
    assert "already green at open" in verdict.checks[0].detail


def test_still_red_at_close_is_rejected() -> None:
    verdict = grade([Check("a", False)], [Check("a", False)])
    assert verdict.outcome is Outcome.REJECTED
    assert "still red" in verdict.reason


def test_one_red_criterion_rejects_the_whole_mission() -> None:
    verdict = grade(
        [Check("a", False), Check("b", False)],
        [Check("a", True), Check("b", False)],
    )
    assert verdict.outcome is Outcome.REJECTED


def test_prose_criterion_forces_needs_human_even_when_everything_else_passed() -> None:
    verdict = grade(
        [Check("a", False), Check("p", None)],
        [Check("a", True), Check("p", None)],
    )
    assert verdict.outcome is Outcome.NEEDS_HUMAN
    assert "p" in verdict.reason


def test_criterion_absent_at_open_is_not_proof() -> None:
    verdict = grade([], [Check("a", True)])
    assert verdict.outcome is Outcome.NEEDS_HUMAN
    assert "not measured at open" in verdict.checks[0].detail


def test_a_mission_with_no_criteria_is_never_accepted() -> None:
    verdict = grade([], [])
    assert verdict.outcome is Outcome.NEEDS_HUMAN
    assert "no criteria" in verdict.reason


def test_reads_criteria_straight_out_of_a_milestone_description() -> None:
    # The whole point of reusing the existing `done_when:` grammar: no schema
    # migration, and an all-prose milestone keeps working untouched.
    from mythings.goals import parse_description

    statement, done_when, _ = parse_description(
        "statement: The heartbeat must actually alert.\n"
        "done_when: $ pytest tests/test_heartbeat.py::test_alerts\n"
        "done_when: pr_merged MyThingsLab/my-fleet#101\n"
        "done_when: the operator sees it on their phone\n"
    )
    assert statement == "The heartbeat must actually alert."
    kinds = [c.kind for c in parse_criteria(done_when)]
    assert kinds == [CriterionKind.COMMAND, CriterionKind.PR_MERGED, CriterionKind.PROSE]


def test_legacy_all_prose_milestone_still_parses() -> None:
    from mythings.goals import parse_description

    _, done_when, _ = parse_description("done_when: the fleet stops dropping work on the floor")
    criteria = parse_criteria(done_when)
    assert [c.executable for c in criteria] == [False]


def test_end_to_end_red_then_green(tmp_path: Path) -> None:
    target = tmp_path / "fixed.txt"
    script = f"import pathlib,sys; sys.exit(0 if pathlib.Path({str(target)!r}).exists() else 1)"
    criteria = parse_criteria([f"$ {sys.executable} -c {script!r}"])

    opening = run_criteria(criteria, cwd=tmp_path)
    assert already_green(opening) == ()

    target.write_text("the work happened")
    closing = run_criteria(criteria, cwd=tmp_path)

    verdict = grade(opening, closing)
    assert verdict.outcome is Outcome.ACCEPTED
