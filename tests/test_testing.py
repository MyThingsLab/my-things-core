from __future__ import annotations

import os

import pytest

from mythings.engine import EngineRequest
from mythings.ledger import Ledger
from mythings.testing import (
    FakeCliRunner,
    FakeGh,
    FakeTransport,
    ScriptedEngine,
    fake_fetch,
    ledger_entry,
    make_git_repo,
    make_ledgers,
)


def test_fake_transport_records_sent_messages_and_commands() -> None:
    transport = FakeTransport(updates=[{"update_id": 1}])
    msg_id = transport.send_message("hello", chat_id="123", markdown=True)
    assert msg_id == 1
    assert transport.sent == [("hello", None)]
    assert transport.sent_to == ["123"]
    assert transport.fetch_updates() == [{"update_id": 1}]


def test_fake_cli_runner_records_and_matches() -> None:
    runner = FakeCliRunner({("cmd", "sub"): "out\n"})
    assert runner(["cmd", "sub", "arg"]) == "out\n"
    assert runner(["cmd", "other"]) == "ok"
    assert runner.saw("cmd", "sub")



def test_fake_gh_fixed_reply_and_recording() -> None:
    gh = FakeGh({("issue", "comment"): "https://github.com/o/r/issues/9#issuecomment-1\n"})
    out = gh(["issue", "comment", "9", "--body", "hi"])
    assert out.startswith("https://")
    assert gh.calls == [["issue", "comment", "9", "--body", "hi"]]
    assert gh.saw("issue", "comment")
    assert not gh.saw("pr", "create")


def test_fake_gh_callable_reply_sees_argv() -> None:
    gh = FakeGh({("pr", "create"): lambda argv: f"https://github.com/o/r/pull/{len(argv)}\n"})
    assert gh(["pr", "create", "--title", "t"]) == "https://github.com/o/r/pull/4\n"


def test_fake_gh_falls_back_to_single_token_key() -> None:
    gh = FakeGh({("api",): "{}"})
    assert gh(["api", "repos/o/r"]) == "{}"


def test_fake_gh_unexpected_call_fails_loudly() -> None:
    gh = FakeGh()
    with pytest.raises(AssertionError, match="unexpected gh call"):
        gh(["issue", "edit", "1"])
    assert gh.calls == [["issue", "edit", "1"]]


def test_scripted_engine_records_and_replies() -> None:
    engine = ScriptedEngine('{"plan": []}', data={"k": 1})
    result = engine.run(EngineRequest(prompt="p", system="s"))
    assert result.text == '{"plan": []}'
    assert result.data == {"k": 1}
    assert engine.calls == [EngineRequest(prompt="p", system="s")]


def test_scripted_engine_defaults_to_empty_spy() -> None:
    engine = ScriptedEngine()
    result = engine.run(EngineRequest(prompt="p"))
    assert result.text == ""
    assert result.data == {}
    assert len(engine.calls) == 1


def test_fake_fetch_matches_by_substring_and_encodes() -> None:
    fetch = fake_fetch(
        {
            "openlibrary.org": {"ISBN:1": {"title": "T"}},
            "example.com/raw": b"\x00\x01",
            "example.com/text": "plain",
        }
    )
    assert fetch("https://openlibrary.org/api?bibkeys=ISBN:1") == b'{"ISBN:1": {"title": "T"}}'
    assert fetch("https://example.com/raw") == b"\x00\x01"
    assert fetch("https://example.com/text") == b"plain"


def test_fake_fetch_default_and_miss() -> None:
    assert fake_fetch(default=b"{}")("https://anything") == b"{}"
    with pytest.raises(AssertionError, match="unexpected fetch url"):
        fake_fetch()("https://anything")


def test_ledger_entry_defaults_are_deterministic() -> None:
    entry = ledger_entry("my-reporter", "report", "success", extra=1)
    assert entry.ts == "2026-07-06T00:00:00Z"
    assert entry.detail == ""
    assert entry.data == {"extra": 1}


def test_make_ledgers_round_trips_through_ledger(tmp_path) -> None:
    shared = [ledger_entry("t", "build", "success")]
    dev = [ledger_entry("claude-code", "decision", "recorded", "why")]
    ledger_path, root = make_ledgers(tmp_path / "repo", shared=shared, dev=dev)
    assert Ledger(ledger_path).read() == shared
    assert Ledger(root / "dev-ledger" / "2026-07-06.jsonl").read() == dev


def test_make_git_repo_pushes_initial_commit(tmp_path, clean_git_env) -> None:
    repo = make_git_repo(tmp_path, files={"README.md": "# x\n", "src/pkg/__init__.py": ""})
    assert repo.read_committed("main", "README.md") == "# x\n"
    repo.git("checkout", "-b", "feature")
    (repo.path / "new.txt").write_text("hi\n", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-m", "add")
    repo.git("push", "-u", "origin", "feature")
    assert repo.read_committed("feature", "new.txt") == "hi\n"


@pytest.fixture
def _dirty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/nowhere")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")


def test_clean_git_env_unsets_git_vars(_dirty_env, clean_git_env) -> None:
    assert "GIT_DIR" not in os.environ
    assert os.environ.get("GITHUB_ACTIONS") == "true"


def test_attended_env_unsets_github_actions(_dirty_env, attended_env) -> None:
    assert "GITHUB_ACTIONS" not in os.environ
    assert os.environ.get("GIT_DIR") == "/nowhere"
