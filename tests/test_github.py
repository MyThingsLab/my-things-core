import json

import pytest

from mythings.github import CIStatus, GitHub, GitHubError, _pr_number, _rollup_status


class FakeGh:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self.reply


def test_list_issues_parses_and_flattens_labels() -> None:
    payload = json.dumps(
        [
            {
                "number": 7,
                "title": "fix parser",
                "body": "it crashes",
                "url": "https://github.com/o/r/issues/7",
                "labels": [{"name": "bug"}, {"name": "p1"}],
            }
        ]
    )
    fake = FakeGh(payload)
    gh = GitHub(runner=fake)

    issues = gh.list_issues(labels=["bug"], limit=5)

    assert len(issues) == 1
    assert issues[0].number == 7
    assert issues[0].labels == ["bug", "p1"]
    argv = fake.calls[0]
    assert argv[:2] == ["issue", "list"]
    assert "--label" in argv and "bug" in argv
    assert "5" in argv


def test_repo_flag_is_appended_when_set() -> None:
    fake = FakeGh("[]")
    GitHub(repo="o/r", runner=fake).list_issues()
    assert fake.calls[0][-2:] == ["--repo", "o/r"]


def test_open_pr_extracts_number_from_url() -> None:
    fake = FakeGh("https://github.com/o/r/pull/42\n")
    pr = GitHub(runner=fake).open_pr(
        title="t", body="b", base="main", head="feature", draft=True
    )
    assert pr.number == 42
    assert "--draft" in fake.calls[0]


def test_gh_error_raises() -> None:
    def boom(argv: list[str]) -> str:
        raise GitHubError("nope")

    with pytest.raises(GitHubError):
        GitHub(runner=boom).list_issues()


def test_pr_number_parsing() -> None:
    assert _pr_number("https://github.com/o/r/pull/99") == 99
    assert _pr_number("https://github.com/o/r/pull/99/") == 99


def test_rollup_status_aggregation() -> None:
    assert _rollup_status([]) is CIStatus.NONE
    assert _rollup_status([{"status": "COMPLETED", "conclusion": "SUCCESS"}]) is CIStatus.SUCCESS
    assert _rollup_status([{"status": "IN_PROGRESS"}]) is CIStatus.PENDING
    assert (
        _rollup_status(
            [
                {"status": "COMPLETED", "conclusion": "SUCCESS"},
                {"status": "COMPLETED", "conclusion": "FAILURE"},
            ]
        )
        is CIStatus.FAILURE
    )
    # A StatusContext uses `state` rather than status/conclusion.
    assert _rollup_status([{"state": "SUCCESS"}]) is CIStatus.SUCCESS
    assert _rollup_status([{"state": "PENDING"}]) is CIStatus.PENDING
    # A failed StatusContext reports either FAILURE or ERROR; both are failures.
    assert _rollup_status([{"state": "FAILURE"}]) is CIStatus.FAILURE
    assert _rollup_status([{"state": "ERROR"}]) is CIStatus.FAILURE
    assert _rollup_status([{"state": "SUCCESS"}, {"state": "ERROR"}]) is CIStatus.FAILURE


def test_pr_status_reads_rollup() -> None:
    fake = FakeGh(json.dumps({"statusCheckRollup": [{"state": "SUCCESS"}]}))
    assert GitHub(runner=fake).pr_status(3) is CIStatus.SUCCESS
