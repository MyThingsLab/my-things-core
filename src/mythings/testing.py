from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Imported only from test suites (via `pytest_plugins = ("mythings.testing",)`),
# never at tool runtime — so depending on pytest here does not violate the
# dependency-free-runtime rule.
import pytest

from .engine import EngineRequest, EngineResult
from .ledger import Ledger, LedgerEntry

GhReply = str | Callable[[list[str]], str]


class FakeGh:
    # Fakes the `gh` subprocess boundary (github.Runner). Replies are keyed by
    # subcommand prefix; a call with no matching key fails the test loudly so a
    # fake never silently absorbs an unexpected side effect.
    def __init__(self, responses: dict[tuple[str, ...], GhReply] | None = None) -> None:
        self.responses: dict[tuple[str, ...], GhReply] = dict(responses or {})
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        for key in (tuple(argv[:2]), tuple(argv[:1])):
            if key in self.responses:
                reply = self.responses[key]
                return reply(argv) if callable(reply) else reply
        raise AssertionError(f"unexpected gh call: {argv}")

    def saw(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)


class ScriptedEngine:
    # An Engine that records every request and returns one canned reply.
    # The spy case is the default: ScriptedEngine() replies with empty text.
    def __init__(self, reply: str = "", *, data: dict[str, Any] | None = None) -> None:
        self.reply = reply
        self.data = data or {}
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text=self.reply, data=self.data)


FetchReply = bytes | str | dict[str, Any]
Fetch = Callable[..., bytes]


def fake_fetch(
    responses: dict[str, FetchReply] | None = None, *, default: bytes | None = None
) -> Fetch:
    table = dict(responses or {})

    def _fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
        for key, value in table.items():
            if key in url:
                if isinstance(value, bytes):
                    return value
                if isinstance(value, str):
                    return value.encode()
                return json.dumps(value).encode()
        if default is not None:
            return default
        raise AssertionError(f"unexpected fetch url: {url}")

    return _fetch


def ledger_entry(
    tool: str,
    kind: str,
    outcome: str,
    detail: str = "",
    ts: str = "2026-07-06T00:00:00Z",
    **data: Any,
) -> LedgerEntry:
    return LedgerEntry(tool=tool, kind=kind, outcome=outcome, detail=detail, ts=ts, data=data)


def make_ledgers(
    root: Path,
    *,
    shared: Iterable[LedgerEntry] = (),
    dev: Iterable[LedgerEntry] = (),
    dev_name: str = "2026-07-06.jsonl",
) -> tuple[Path, Path]:
    (root / "dev-ledger").mkdir(parents=True, exist_ok=True)
    ledger_path = root / ".mythings" / "ledger.jsonl"
    shared_ledger = Ledger(ledger_path)
    for entry in shared:
        shared_ledger.append(entry)
    dev_ledger = Ledger(root / "dev-ledger" / dev_name)
    for entry in dev:
        dev_ledger.append(entry)
    return ledger_path, root


@dataclass(frozen=True)
class GitRepo:
    path: Path
    origin: Path

    def git(self, *argv: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.path), *argv], check=True, capture_output=True, text=True
        )
        return proc.stdout

    def read_committed(self, branch: str, path: str) -> str:
        # Reads from the bare origin, not the worktree: asserts what was
        # actually pushed, not what merely sits on disk.
        proc = subprocess.run(
            ["git", "-C", str(self.origin), "show", f"{branch}:{path}"],
            capture_output=True,
            text=True,
        )
        return proc.stdout


def make_git_repo(
    tmp_path: Path, *, files: dict[str, str] | None = None, branch: str = "main"
) -> GitRepo:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    path = tmp_path / "work"
    path.mkdir()
    for name, content in (files or {"README.md": "# repo\n"}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    repo = GitRepo(path=path, origin=origin)
    repo.git("init", "-b", branch)
    repo.git("config", "user.email", "test@example.com")
    repo.git("config", "user.name", "Test")
    repo.git("add", "-A")
    repo.git("commit", "-m", "init")
    repo.git("remote", "add", "origin", str(origin))
    repo.git("push", "-u", "origin", branch)
    return repo


@pytest.fixture
def clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # pre-commit (and any hook-launched pytest) exports GIT_* vars that would
    # point real-git tests at the developer's own repo instead of tmp_path.
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def attended_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default the suite to the attended path (a human is present). CI sets
    # GITHUB_ACTIONS=true, which otherwise collapses Policy ASKs to DENY
    # (fail-closed) — a real behavior a suite must opt into deliberately,
    # not inherit from the runner's env.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


class FakeTransport:
    # Mocks the Telegram HTTP transport boundary (send_message, fetch_updates, etc.)
    def __init__(self, *, updates: list[dict] | None = None) -> None:
        self.sent: list[tuple[str, Any]] = []
        self.sent_to: list[str | None] = []
        self.keyboards: list[tuple[tuple[str, ...], ...] | None] = []
        self.commands_set: list[tuple[tuple[str, str], ...]] = []
        self.fetched: list[tuple[int | None, float]] = []
        self.answered: list[str] = []
        self.markdown: list[bool] = []
        self.actions: list[tuple[str, str | None]] = []
        self.cleared: list[int] = []
        self.edits: list[tuple[int, str]] = []
        self.answers: list[tuple[str, str]] = []
        self.alerts: list[bool] = []
        self.reply_to: list[int | None] = []
        self._updates = updates or []
        self._next_id = 1

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        inline: Any = None,
        keyboard: tuple[tuple[str, ...], ...] | None = None,
        markdown: bool = False,
        reply_to_message_id: int | None = None,
    ) -> int:
        self.sent.append((text, inline))
        self.sent_to.append(chat_id)
        self.keyboards.append(keyboard)
        self.markdown.append(markdown)
        self.reply_to.append(reply_to_message_id)
        message_id = self._next_id
        self._next_id += 1
        return message_id

    def send_chat_action(self, action: str, *, chat_id: str | None = None) -> None:
        self.actions.append((action, chat_id))

    def clear_inline_keyboard(self, message_id: int, *, chat_id: str | None = None) -> None:
        self.cleared.append(message_id)

    def edit_message_text(self, message_id: int, text: str, *, chat_id: str | None = None) -> None:
        self.edits.append((message_id, text))

    def set_my_commands(self, commands: tuple[tuple[str, str], ...]) -> None:
        self.commands_set.append(commands)

    def answer_callback_query(
        self, callback_query_id: str, *, text: str = "", alert: bool = False
    ) -> None:
        self.answered.append(callback_query_id)
        self.answers.append((callback_query_id, text))
        self.alerts.append(alert)

    def fetch_updates(self, *, offset: int | None = None, timeout: float = 0) -> list[dict]:
        self.fetched.append((offset, timeout))
        if offset is None:
            return list(self._updates)
        return [u for u in self._updates if u["update_id"] >= offset]


class FakeCliRunner:
    # Fakes a CLI subcommand runner. Records invocations and returns canned outputs.
    def __init__(
        self,
        responses: dict[tuple[str, ...], str] | None = None,
        *,
        default_output: str = "ok",
    ) -> None:
        self.responses: dict[tuple[str, ...], str] = dict(responses or {})
        self.calls: list[list[str]] = []
        self.default_output = default_output

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        for key in (tuple(argv[:2]), tuple(argv[:1])):
            if key in self.responses:
                return self.responses[key]
        return self.default_output

    def saw(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)

