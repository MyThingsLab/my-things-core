from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mythings.ledger import Ledger, _utc_now

# Multi-tenancy lives here and nowhere else. Every other core contract assumes a
# single principal: the Ledger is one global append-only file, and tools that
# authenticate (my-server) do it with one shared token. Opening the fleet to
# outside testers needs identity, resumable per-tester state, and a hard cap on
# Engine spend by someone who isn't the operator -- so this module owns all three.
#
# SQLite (stdlib) rather than a database server: core declares no runtime
# dependencies and that stays true. The access shape fits exactly -- one writer
# process, many readers -- and WAL plus a busy timeout covers a second process
# (the bot polling while the server reads) contending for the same file.
#
# Nothing here runs at import: a TesterStore touches disk only when constructed
# with a path, mirroring Ledger(path). The module is inert until a tool opts in.

_SCHEMA_VERSION = 1

# Statements, not one script: sqlite3.executescript() implicitly commits any open
# transaction, which would strand the BEGIN IMMEDIATE that guards concurrent migration.
_SCHEMA = """
CREATE TABLE tester (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    handle       TEXT    NOT NULL UNIQUE,
    chat_id      INTEGER UNIQUE,
    token_hash   TEXT    NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 1,
    engine_quota INTEGER NOT NULL,
    engine_used  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);
CREATE TABLE session (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tester_id      INTEGER NOT NULL REFERENCES tester(id),
    started_at     TEXT    NOT NULL,
    last_active_at TEXT    NOT NULL,
    status         TEXT    NOT NULL
);
CREATE TABLE turn (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES session(id),
    seq          INTEGER NOT NULL,
    role         TEXT    NOT NULL,
    command      TEXT    NOT NULL DEFAULT '',
    content      TEXT    NOT NULL DEFAULT '',
    engine_calls INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX turn_by_session ON turn (session_id, seq);
"""

_SCHEMA_STATEMENTS = [s.strip() for s in _SCHEMA.split(";") if s.strip()]

ACTIVE = "active"
CLOSED = "closed"


@dataclass(frozen=True)
class Tester:
    # pytest collects any class named Test* it finds imported in a test module.
    # These are records and a store, not test cases.
    __test__ = False

    id: int
    handle: str
    chat_id: int | None
    enabled: bool
    engine_quota: int
    engine_used: int
    created_at: str

    @property
    def engine_remaining(self) -> int:
        return max(0, self.engine_quota - self.engine_used)


@dataclass(frozen=True)
class Session:
    id: int
    tester_id: int
    started_at: str
    last_active_at: str
    status: str


@dataclass(frozen=True)
class Turn:
    id: int
    session_id: int
    seq: int
    role: str
    command: str
    content: str
    engine_calls: int
    created_at: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tester(row: sqlite3.Row) -> Tester:
    return Tester(
        id=row["id"],
        handle=row["handle"],
        chat_id=row["chat_id"],
        enabled=bool(row["enabled"]),
        engine_quota=row["engine_quota"],
        engine_used=row["engine_used"],
        created_at=row["created_at"],
    )


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        tester_id=row["tester_id"],
        started_at=row["started_at"],
        last_active_at=row["last_active_at"],
        status=row["status"],
    )


def _turn(row: sqlite3.Row) -> Turn:
    return Turn(
        id=row["id"],
        session_id=row["session_id"],
        seq=row["seq"],
        role=row["role"],
        command=row["command"],
        content=row["content"],
        engine_calls=row["engine_calls"],
        created_at=row["created_at"],
    )


class TesterStore:
    __test__ = False

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None disables the driver's implicit transaction handling
        # so `_immediate()` can open BEGIN IMMEDIATE itself -- the write lock must
        # be taken before the quota row is read, not upgraded after.
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TesterStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        with self._immediate():
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _SCHEMA_STATEMENTS:
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    @contextmanager
    def _immediate(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def register(
        self,
        handle: str,
        *,
        engine_quota: int,
        chat_id: int | None = None,
    ) -> tuple[Tester, str]:
        token = secrets.token_urlsafe(32)
        now = _utc_now()
        with self._immediate():
            cur = self._conn.execute(
                "INSERT INTO tester (handle, chat_id, token_hash, engine_quota, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (handle, chat_id, _hash_token(token), engine_quota, now),
            )
            row = self._conn.execute(
                "SELECT * FROM tester WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        # The raw token is returned exactly once and never stored -- only its
        # sha256 reaches disk. A lost token is re-issued, never recovered.
        return _tester(row), token

    def authenticate(self, token: str) -> Tester | None:
        row = self._conn.execute(
            "SELECT * FROM tester WHERE token_hash = ? AND enabled = 1",
            (_hash_token(token),),
        ).fetchone()
        return _tester(row) if row else None

    def by_chat_id(self, chat_id: int) -> Tester | None:
        row = self._conn.execute(
            "SELECT * FROM tester WHERE chat_id = ? AND enabled = 1", (chat_id,)
        ).fetchone()
        return _tester(row) if row else None

    def get(self, tester_id: int) -> Tester | None:
        row = self._conn.execute("SELECT * FROM tester WHERE id = ?", (tester_id,)).fetchone()
        return _tester(row) if row else None

    def set_enabled(self, tester_id: int, enabled: bool) -> None:
        with self._immediate():
            self._conn.execute(
                "UPDATE tester SET enabled = ? WHERE id = ?", (int(enabled), tester_id)
            )

    def reserve_engine_call(self, tester_id: int) -> bool:
        # The whole quota decision is this one statement: the guard lives in the
        # WHERE clause, so a read-then-write race cannot oversell. Callers reserve
        # *before* spending; a crash mid-call over-counts (safe) rather than
        # over-spends (not). Refusal is the default -- no row updated means no.
        with self._immediate():
            cur = self._conn.execute(
                "UPDATE tester SET engine_used = engine_used + 1 "
                "WHERE id = ? AND enabled = 1 AND engine_used < engine_quota",
                (tester_id,),
            )
            return cur.rowcount == 1

    def release_engine_call(self, tester_id: int) -> None:
        with self._immediate():
            self._conn.execute(
                "UPDATE tester SET engine_used = engine_used - 1 WHERE id = ? AND engine_used > 0",
                (tester_id,),
            )

    def start_session(self, tester_id: int) -> Session:
        now = _utc_now()
        with self._immediate():
            # One active session per tester: starting a new one closes the old.
            self._conn.execute(
                "UPDATE session SET status = ? WHERE tester_id = ? AND status = ?",
                (CLOSED, tester_id, ACTIVE),
            )
            cur = self._conn.execute(
                "INSERT INTO session (tester_id, started_at, last_active_at, status) "
                "VALUES (?, ?, ?, ?)",
                (tester_id, now, now, ACTIVE),
            )
            row = self._conn.execute(
                "SELECT * FROM session WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return _session(row)

    def append_turn(
        self,
        session_id: int,
        role: str,
        *,
        command: str = "",
        content: str = "",
        engine_calls: int = 0,
    ) -> Turn:
        now = _utc_now()
        with self._immediate():
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM turn WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            cur = self._conn.execute(
                "INSERT INTO turn (session_id, seq, role, command, content, engine_calls, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, seq, role, command, content, engine_calls, now),
            )
            self._conn.execute(
                "UPDATE session SET last_active_at = ? WHERE id = ?", (now, session_id)
            )
            row = self._conn.execute("SELECT * FROM turn WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _turn(row)

    def resume(self, tester_id: int) -> tuple[Session, list[Turn]] | None:
        row = self._conn.execute(
            "SELECT * FROM session WHERE tester_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (tester_id, ACTIVE),
        ).fetchone()
        if row is None:
            return None
        session = _session(row)
        turns = [
            _turn(r)
            for r in self._conn.execute(
                "SELECT * FROM turn WHERE session_id = ? ORDER BY seq", (session.id,)
            )
        ]
        return session, turns

    def ledger_for(self, tester: Tester) -> Ledger:
        return Ledger(self.path.parent / "tester-ledgers" / f"{tester.id}.jsonl")
