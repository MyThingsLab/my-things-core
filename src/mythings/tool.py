from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mythings.engine import Engine, EngineRequest, EngineResult
from mythings.github import GitHub, Issue
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import ALLOW, Action, Decision, Policy, PolicyResult


class DefaultPolicy:
    """Default permissive policy returning ALLOW for all actions."""

    def evaluate(self, action: Action) -> PolicyResult:
        return ALLOW


def _default_run_git(tree: Path, argv: list[str]) -> None:
    proc = subprocess.run(["git", *argv], cwd=tree, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )


@dataclass(frozen=True)
class ToolRunResult:
    """Standard execution result returned by BaseToolRunner."""

    outcome: str  # success | noop | skipped | denied | failure
    detail: str
    issue: int | None = None
    pr: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


class BaseToolRunner:
    """Base runner for My[X] tools picking issues and executing workflow steps."""

    def __init__(
        self,
        *,
        repo: str | Path = ".",
        ledger: Ledger | None = None,
        github: GitHub | None = None,
        engine: Engine | None = None,
        policy: Policy | None = None,
        base: str = "main",
        label: str = "",
        git: Callable[[Path, list[str]], None] | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.ledger = ledger
        self.github = github or GitHub(repo=str(repo) if isinstance(repo, str) else None)
        self.engine = engine
        self.policy = policy or DefaultPolicy()
        self.base = base
        self.label = label
        self._git = git or _default_run_git

    def pick_issue(self, issue_number: int | None = None) -> Issue | None:
        """Fetch issue by number or pick the first open issue with self.label."""
        if not self.label:
            if issue_number is not None:
                return self.github.get_issue(issue_number)
            return None
        issues = self.github.list_issues(labels=[self.label])
        if issue_number is not None:
            return next((i for i in issues if i.number == issue_number), None)
        return min(issues, key=lambda i: i.number) if issues else None

    def prework(self, issue: Issue) -> str:
        """Seam: deterministic pre-work gathering context for Engine call."""
        return issue.body

    def request(self, issue: Issue, context: str) -> EngineRequest:
        """Seam: construct single EngineRequest for the judgment call."""
        prompt = f"{issue.title}\n\n{context}" if context else issue.title
        return EngineRequest(prompt=prompt)

    def apply(self, tree: Path, issue: Issue, result: EngineResult) -> str | None:
        """Seam: apply Engine reply into isolated worktree. Return relpath or None."""
        return None

    def run_issue_workflow(
        self,
        tool_name: str,
        ledger_kind: str,
        issue_number: int | None = None,
    ) -> ToolRunResult:
        """Execute standard issue pickup -> prework -> engine -> workspace -> PR workflow."""
        issue = self.pick_issue(issue_number)
        if issue is None:
            detail = f"no open '{self.label}' issue" + (
                f" #{issue_number}" if issue_number is not None else ""
            )
            if self.ledger:
                self.ledger.record(tool_name, ledger_kind, "skipped", detail)
            return ToolRunResult(outcome="skipped", detail=detail)

        context = self.prework(issue)
        assert self.engine is not None, "engine must be configured before running workflow"
        engine_result = self.engine.run(self.request(issue, context))

        with Workspace(self.repo, base_ref=f"origin/{self.base}") as tree:
            relpath = self.apply(tree, issue, engine_result)
            if relpath is None:
                detail = f"nothing to change for #{issue.number}"
                if self.ledger:
                    self.ledger.record(tool_name, ledger_kind, "noop", detail, issue=issue.number)
                return ToolRunResult(outcome="noop", detail=detail, issue=issue.number)

            branch = f"{self.label}/{issue.number}"
            gate = self.policy.evaluate(
                Action(kind="bash", payload={"command": f"gh pr create --head {branch}"})
            )
            if gate.under(unattended=in_github_actions()) is not Decision.ALLOW:
                detail = f"policy blocked the PR for #{issue.number}: {gate.reason or gate.rule}"
                if self.ledger:
                    self.ledger.record(tool_name, ledger_kind, "denied", detail, issue=issue.number)
                return ToolRunResult(outcome="denied", detail=detail, issue=issue.number)

            self._git(tree, ["checkout", "-b", branch])
            self._git(tree, ["add", relpath])
            self._git(tree, ["commit", "-m", f"{tool_name}: {issue.title}"])
            self._git(tree, ["push", "-u", "origin", branch])
            pr = self.github.open_pr(
                title=issue.title,
                body=f"Closes #{issue.number}.",
                base=self.base,
                head=branch,
                draft=True,
            )

        if self.ledger:
            self.ledger.record(
                tool_name,
                ledger_kind,
                "success",
                f"PR #{pr.number} for #{issue.number}",
                issue=issue.number,
                pr=pr.number,
            )
        return ToolRunResult(
            outcome="success",
            detail=f"opened draft PR #{pr.number}",
            issue=issue.number,
            pr=pr.number,
        )
