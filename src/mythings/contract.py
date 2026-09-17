from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mythings.policy import Action, Decision, Policy
from mythings.session import Check, Outcome, Verdict

DEFAULT_TIMEOUT = 600

# Commands run argv-only (shell=False), because a milestone description is a
# GitHub field any write-access account can edit and `shell=True` there is
# remote code execution. That already makes a pipeline harmless -- it would be
# passed as a literal argument -- but silently doing so turns an operator's
# intended pipeline into a check that measures something else. So a line whose
# *tokens* include a bare shell operator degrades to prose instead. The test is
# deliberately post-split: `python -c "import x; y"` keeps its semicolon inside
# one argument and is fine, while `pytest | grep` yields a standalone "|".
_SHELL_OPERATORS = frozenset({"|", "||", "&", "&&", ";", ";;", ">", ">>", "<", "<<", "2>", "&>"})


class CriterionKind(StrEnum):
    COMMAND = "command"
    CI_GREEN = "ci_green"
    PR_MERGED = "pr_merged"
    ISSUE_CLOSED = "issue_closed"
    PROSE = "prose"


@dataclass(frozen=True)
class Criterion:
    kind: CriterionKind
    raw: str
    argv: tuple[str, ...] = ()
    repo: str = ""
    number: int | None = None
    # Why an otherwise-executable-looking line ended up prose. Empty for lines
    # that were never meant to be executable.
    note: str = ""

    @property
    def executable(self) -> bool:
        return self.kind is not CriterionKind.PROSE

    @property
    def name(self) -> str:
        # Stable across an open/close pair so the two runs can be zipped by
        # name: derived only from the criterion text, never from its result.
        body = self.raw.strip()
        return f"{self.kind.value}:{body[:80]}"


def _parse_ref(rest: str) -> tuple[str, int] | None:
    repo, _, number = rest.strip().partition("#")
    if not repo.strip() or not number.strip().isdigit():
        return None
    return repo.strip(), int(number)


def parse_criterion(line: str) -> Criterion:
    raw = line.strip()
    if not raw:
        return Criterion(kind=CriterionKind.PROSE, raw=raw)

    if raw.startswith("$"):
        command = raw[1:].strip()
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return Criterion(kind=CriterionKind.PROSE, raw=raw, note=f"unparsable command: {exc}")
        if not argv:
            return Criterion(kind=CriterionKind.PROSE, raw=raw, note="empty command")
        operator = next((token for token in argv if token in _SHELL_OPERATORS), "")
        if operator:
            return Criterion(
                kind=CriterionKind.PROSE,
                raw=raw,
                note=f"{operator!r} needs a shell; commands run argv-only, so a human judges this",
            )
        return Criterion(kind=CriterionKind.COMMAND, raw=raw, argv=tuple(argv))

    verb, _, rest = raw.partition(" ")
    keyword = verb.strip().lower()

    if keyword == CriterionKind.CI_GREEN.value:
        repo = rest.strip()
        if repo:
            return Criterion(kind=CriterionKind.CI_GREEN, raw=raw, repo=repo)
        return Criterion(kind=CriterionKind.PROSE, raw=raw, note="ci_green needs a repo")

    if keyword in (CriterionKind.PR_MERGED.value, CriterionKind.ISSUE_CLOSED.value):
        ref = _parse_ref(rest)
        if ref is None:
            return Criterion(
                kind=CriterionKind.PROSE, raw=raw, note=f"{keyword} needs <owner/repo>#<number>"
            )
        repo, number = ref
        return Criterion(kind=CriterionKind(keyword), raw=raw, repo=repo, number=number)

    return Criterion(kind=CriterionKind.PROSE, raw=raw)


def parse_criteria(done_when: Sequence[str]) -> tuple[Criterion, ...]:
    return tuple(parse_criterion(line) for line in done_when)


def _unevaluable(criterion: Criterion, detail: str) -> Check:
    # None, never False: "I could not run this" and "I ran it and it failed"
    # have opposite follow-ups, and collapsing them is how a gate starts
    # reporting green for work it never checked.
    return Check(name=criterion.name, passed=None, detail=detail)


def _run_command(criterion: Criterion, *, cwd: Path, timeout: int) -> Check:
    try:
        proc = subprocess.run(  # noqa: S603 -- argv-only by construction, shell=False
            list(criterion.argv),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError:
        return _unevaluable(criterion, f"command not found: {criterion.argv[0]}")
    except subprocess.TimeoutExpired:
        return _unevaluable(criterion, f"timed out after {timeout}s")
    except OSError as exc:
        return _unevaluable(criterion, f"could not run: {exc}")

    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    last = tail[-1][:200] if tail else ""
    return Check(
        name=criterion.name,
        passed=proc.returncode == 0,
        detail=f"exit {proc.returncode}" + (f" — {last}" if last else ""),
    )


def _gh_json(runner, argv: list[str]):
    raw = runner(argv)
    return json.loads(raw) if raw.strip() else None


def _run_github(criterion: Criterion, *, runner) -> Check:
    try:
        if criterion.kind is CriterionKind.CI_GREEN:
            runs = _gh_json(
                runner,
                [
                    "run",
                    "list",
                    "--repo",
                    criterion.repo,
                    "--branch",
                    "main",
                    "--limit",
                    "1",
                    "--json",
                    "conclusion",
                ],
            )
            if not runs:
                return _unevaluable(criterion, f"no CI runs on {criterion.repo}@main")
            conclusion = (runs[0].get("conclusion") or "").lower()
            if not conclusion:
                return _unevaluable(criterion, "latest run still in progress")
            return Check(
                name=criterion.name,
                passed=conclusion == "success",
                detail=f"{criterion.repo}@main: {conclusion}",
            )

        if criterion.kind is CriterionKind.PR_MERGED:
            obj = _gh_json(
                runner,
                ["pr", "view", str(criterion.number), "--repo", criterion.repo, "--json", "state"],
            )
            state = ((obj or {}).get("state") or "").upper()
            if not state:
                return _unevaluable(criterion, "could not read PR state")
            return Check(
                name=criterion.name,
                passed=state == "MERGED",
                detail=f"{criterion.repo}#{criterion.number}: {state}",
            )

        obj = _gh_json(
            runner,
            ["issue", "view", str(criterion.number), "--repo", criterion.repo, "--json", "state"],
        )
        state = ((obj or {}).get("state") or "").upper()
        if not state:
            return _unevaluable(criterion, "could not read issue state")
        return Check(
            name=criterion.name,
            passed=state == "CLOSED",
            detail=f"{criterion.repo}#{criterion.number}: {state}",
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _unevaluable(criterion, f"github lookup failed: {exc}")


def run_criteria(
    criteria: Sequence[Criterion],
    *,
    cwd: Path,
    policy: Policy | None = None,
    runner=None,
    unattended: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[Check, ...]:
    checks: list[Check] = []
    for criterion in criteria:
        if criterion.kind is CriterionKind.PROSE:
            detail = criterion.note or "prose criterion — a human must judge this"
            checks.append(_unevaluable(criterion, detail))
            continue

        if policy is not None:
            action = Action(
                kind="run-check",
                payload={
                    "criterion": criterion.kind.value,
                    "argv": list(criterion.argv),
                    "repo": criterion.repo,
                    "cwd": str(cwd),
                },
            )
            # Core owns no ask channel -- that is myguard's, and core stays
            # dependency-free -- so an ASK it cannot resolve reports unevaluable
            # rather than running. Allowing it here would quietly bypass the
            # fleet's human gate; a caller holding a Guard resolves the ASK
            # first and passes a policy that already reflects the answer.
            result = policy.evaluate(action)
            decision = result.under(unattended=unattended)
            if decision is not Decision.ALLOW:
                why = result.reason or decision.value
                checks.append(_unevaluable(criterion, f"policy returned {decision.value}: {why}"))
                continue

        if criterion.kind is CriterionKind.COMMAND:
            checks.append(_run_command(criterion, cwd=cwd, timeout=timeout))
        elif runner is None:
            checks.append(_unevaluable(criterion, "no GitHub runner supplied"))
        else:
            checks.append(_run_github(criterion, runner=runner))
    return tuple(checks)


def already_green(checks: Sequence[Check]) -> tuple[str, ...]:
    return tuple(check.name for check in checks if check.passed is True)


def grade(opening: Sequence[Check], closing: Sequence[Check]) -> Verdict:
    # A mission is proved by a red->green transition, not by a green reading.
    # A criterion green at open proves nothing about the work that followed --
    # that is precisely how a suite that never ran still reported success -- so
    # it can only ever reach NEEDS_HUMAN here, never ACCEPTED.
    opened = {check.name: check for check in opening}
    graded: list[Check] = []
    for check in closing:
        before = opened.get(check.name)
        if before is None:
            graded.append(Check(check.name, None, f"not measured at open — {check.detail}"))
        elif check.passed is None or before.passed is None:
            graded.append(Check(check.name, None, check.detail))
        elif before.passed:
            graded.append(Check(check.name, None, f"already green at open — {check.detail}"))
        elif check.passed:
            graded.append(Check(check.name, True, f"red at open, green at close — {check.detail}"))
        else:
            graded.append(Check(check.name, False, check.detail))

    graded_tuple = tuple(graded)
    if not graded_tuple:
        return Verdict(Outcome.NEEDS_HUMAN, (), "mission declared no criteria")
    if any(check.passed is False for check in graded_tuple):
        failed = [check.name for check in graded_tuple if check.passed is False]
        return Verdict(Outcome.REJECTED, graded_tuple, f"still red: {', '.join(failed)}")
    if any(check.passed is None for check in graded_tuple):
        unproved = [check.name for check in graded_tuple if check.passed is None]
        return Verdict(
            Outcome.NEEDS_HUMAN, graded_tuple, f"not proved by machine: {', '.join(unproved)}"
        )
    return Verdict(Outcome.ACCEPTED, graded_tuple, "every criterion went red to green")
