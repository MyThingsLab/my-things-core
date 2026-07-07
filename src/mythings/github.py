from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

# A Runner takes the argument vector *after* `gh` and returns stdout. The default
# shells out; tests inject a fake so the boundary (the `gh` process) is the only
# thing mocked.
Runner = Callable[[list[str]], str]


class GitHubError(RuntimeError):
    pass


def _gh(argv: list[str]) -> str:
    proc = subprocess.run(["gh", *argv], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitHubError(f"gh {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


class CIStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


_FAILURE_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    url: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str


class GitHub:
    def __init__(self, repo: str | None = None, *, runner: Runner = _gh) -> None:
        self.repo = repo
        self._run = runner

    def _argv(self, argv: list[str]) -> list[str]:
        return [*argv, "--repo", self.repo] if self.repo else argv

    def list_issues(
        self,
        *,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 30,
    ) -> list[Issue]:
        argv = [
            "issue",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,body,labels,url",
        ]
        for label in labels or []:
            argv += ["--label", label]
        raw = json.loads(self._run(self._argv(argv)))
        return [
            Issue(
                number=obj["number"],
                title=obj["title"],
                body=obj.get("body", "") or "",
                url=obj["url"],
                labels=[lbl["name"] for lbl in obj.get("labels", [])],
            )
            for obj in raw
        ]

    def open_pr(
        self,
        *,
        title: str,
        body: str,
        base: str,
        head: str,
        draft: bool = False,
    ) -> PullRequest:
        argv = ["pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
        if draft:
            argv.append("--draft")
        url = self._run(self._argv(argv)).strip().splitlines()[-1]
        return PullRequest(number=_pr_number(url), url=url)

    def pr_status(self, number: int) -> CIStatus:
        argv = ["pr", "view", str(number), "--json", "statusCheckRollup"]
        rollup = json.loads(self._run(self._argv(argv))).get("statusCheckRollup") or []
        return _rollup_status(rollup)

    def create_issue(self, *, title: str, body: str) -> Issue:
        argv = ["issue", "create", "--title", title, "--body", body]
        url = self._run(self._argv(argv)).strip().splitlines()[-1]
        return Issue(number=_issue_number(url), title=title, body=body, url=url)

    def add_labels(self, number: int, labels: list[str]) -> None:
        argv = ["issue", "edit", str(number)]
        for label in labels:
            argv += ["--add-label", label]
        self._run(self._argv(argv))


def _pr_number(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _issue_number(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _rollup_status(rollup: list[dict[str, str]]) -> CIStatus:
    if not rollup:
        return CIStatus.NONE
    saw_pending = False
    for check in rollup:
        # CheckRun carries status/conclusion; StatusContext carries state.
        state = check.get("state")
        if state in _FAILURE_CONCLUSIONS or check.get("conclusion") in _FAILURE_CONCLUSIONS:
            return CIStatus.FAILURE
        completed = check.get("status") == "COMPLETED" or state in {"SUCCESS", "FAILURE", "ERROR"}
        if not completed:
            saw_pending = True
    return CIStatus.PENDING if saw_pending else CIStatus.SUCCESS
