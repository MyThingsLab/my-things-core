from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mythings.github import GitHub, Issue
from mythings.policy import ALLOW, Action, Decision, Policy, PolicyResult


class DefaultPolicy:
    """Default permissive policy returning ALLOW for all actions."""

    def evaluate(self, action: Action) -> PolicyResult:
        return ALLOW


@dataclass
class ToolRunResult:
    """Standard execution result returned by BaseToolRunner."""

    issue: Issue | None
    outcome: str
    detail: str
    data: dict[str, Any]


class BaseToolRunner:
    """Base runner for My[X] tools picking issues and executing workflow steps."""

    def __init__(
        self,
        repo: str,
        label: str,
        *,
        github: GitHub | None = None,
        policy: Policy | None = None,
    ) -> None:
        self.repo = repo
        self.label = label
        self.github = github or GitHub(repo=repo)
        self.policy = policy or DefaultPolicy()

    def pick_issue(self, issue_number: int | None = None) -> Issue | None:
        """Fetch issue by number or pick the first open issue with self.label."""
        if issue_number is not None:
            return self.github.get_issue(issue_number)
        issues = self.github.list_issues(labels=[self.label], state="open", limit=1)
        return issues[0] if issues else None

