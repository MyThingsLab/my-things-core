import argparse
import json

from mythings.engine import ClaudeCLIEngine, GeminiCLIEngine, NoopEngine, build_engine_from_args
from mythings.github import GitHub
from mythings.tool import BaseToolRunner


class FakeGh:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self.reply


def test_build_engine_from_args_returns_expected_instances() -> None:
    args_noop = argparse.Namespace(engine="noop")
    assert isinstance(build_engine_from_args(args_noop), NoopEngine)

    args_claude = argparse.Namespace(engine="claude-cli", model="claude-3-5-sonnet", effort="low")
    eng_claude = build_engine_from_args(args_claude)
    assert isinstance(eng_claude, ClaudeCLIEngine)

    args_gemini = argparse.Namespace(engine="gemini-cli", model="gemini-1.5-pro")
    eng_gemini = build_engine_from_args(args_gemini)
    assert isinstance(eng_gemini, GeminiCLIEngine)


def test_base_tool_runner_picks_issue() -> None:
    payload = json.dumps(
        [
            {
                "number": 15,
                "title": "Do task",
                "body": "task body",
                "url": "https://github.com/org/repo/issues/15",
                "labels": [{"name": "my-tool"}],
            }
        ]
    )
    fake = FakeGh(payload)
    gh = GitHub(repo="org/repo", runner=fake)
    runner = BaseToolRunner(repo="org/repo", label="my-tool", github=gh)

    issue = runner.pick_issue()

    assert issue is not None
    assert issue.number == 15
    assert issue.title == "Do task"
