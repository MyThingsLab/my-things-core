from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from mythings.testers import ACTIVE, CLOSED, TesterStore


def test_register_returns_token_once_and_authenticates(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, token = store.register("ada", engine_quota=5, chat_id=42)

    assert tester.handle == "ada"
    assert tester.chat_id == 42
    assert tester.enabled
    assert tester.engine_used == 0
    assert tester.engine_remaining == 5

    assert store.authenticate(token) == tester
    assert store.authenticate("not-the-token") is None


def test_lookup_by_chat_id(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, _ = store.register("ada", engine_quota=1, chat_id=42)

    assert store.by_chat_id(42) == tester
    assert store.by_chat_id(99) is None


def test_disabled_tester_is_invisible_and_cannot_reserve(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, token = store.register("ada", engine_quota=5, chat_id=42)

    store.set_enabled(tester.id, False)

    assert store.authenticate(token) is None
    assert store.by_chat_id(42) is None
    assert store.reserve_engine_call(tester.id) is False
    assert store.get(tester.id).engine_used == 0


def test_quota_is_fail_closed_at_the_boundary(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, _ = store.register("ada", engine_quota=3)

    assert [store.reserve_engine_call(tester.id) for _ in range(3)] == [True, True, True]
    assert store.reserve_engine_call(tester.id) is False
    assert store.reserve_engine_call(tester.id) is False

    refreshed = store.get(tester.id)
    assert refreshed.engine_used == 3
    assert refreshed.engine_remaining == 0


def test_concurrent_reserve_never_oversells(tmp_path: Path) -> None:
    db = tmp_path / "testers.db"
    store = TesterStore(db)
    tester, _ = store.register("ada", engine_quota=20)

    quota = 20
    workers = 8
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(workers)

    def hammer() -> None:
        # Its own connection: this is the cross-connection race that a single
        # in-process store would never exercise.
        local = TesterStore(db)
        barrier.wait()
        got = [local.reserve_engine_call(tester.id) for _ in range(quota)]
        local.close()
        with lock:
            results.extend(got)

    threads = [threading.Thread(target=hammer) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == quota
    assert store.get(tester.id).engine_used == quota


def test_release_refunds_one_and_never_goes_negative(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, _ = store.register("ada", engine_quota=2)

    store.reserve_engine_call(tester.id)
    store.release_engine_call(tester.id)
    assert store.get(tester.id).engine_used == 0

    store.release_engine_call(tester.id)
    assert store.get(tester.id).engine_used == 0


def test_raw_token_never_reaches_disk(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    _, token = store.register("ada", engine_quota=1)
    store.close()

    needle = token.encode("utf-8")
    written = [p for p in tmp_path.iterdir() if p.is_file()]
    assert written
    for path in written:
        assert needle not in path.read_bytes()


def test_session_turns_resume_in_order(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, _ = store.register("ada", engine_quota=5)

    assert store.resume(tester.id) is None

    session = store.start_session(tester.id)
    store.append_turn(session.id, "tester", command="/idea", content="a bot for x")
    store.append_turn(session.id, "bot", content="verdict: build", engine_calls=1)

    resumed = store.resume(tester.id)
    assert resumed is not None
    got_session, turns = resumed
    assert got_session.id == session.id
    assert got_session.status == ACTIVE
    assert [t.seq for t in turns] == [1, 2]
    assert [t.role for t in turns] == ["tester", "bot"]
    assert turns[1].engine_calls == 1
    assert got_session.last_active_at >= session.started_at


def test_starting_a_session_closes_the_previous_one(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    tester, _ = store.register("ada", engine_quota=5)

    first = store.start_session(tester.id)
    store.append_turn(first.id, "tester", content="old")
    second = store.start_session(tester.id)

    resumed = store.resume(tester.id)
    assert resumed is not None
    session, turns = resumed
    assert session.id == second.id
    assert turns == []

    stale = store._conn.execute("SELECT status FROM session WHERE id = ?", (first.id,)).fetchone()
    assert stale["status"] == CLOSED


def test_each_tester_gets_an_isolated_ledger(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    ada, _ = store.register("ada", engine_quota=1)
    bob, _ = store.register("bob", engine_quota=1)

    ada_ledger = store.ledger_for(ada)
    bob_ledger = store.ledger_for(bob)
    assert ada_ledger.path != bob_ledger.path

    ada_ledger.record("my-idea", "run", "success", detail="ada only")

    assert [e.detail for e in ada_ledger] == ["ada only"]
    assert list(bob_ledger) == []


def test_failed_write_rolls_back_and_leaves_store_usable(tmp_path: Path) -> None:
    store = TesterStore(tmp_path / "testers.db")
    store.register("ada", engine_quota=1)

    with pytest.raises(sqlite3.IntegrityError):
        store.register("ada", engine_quota=1)

    # The rolled-back transaction must not be left open, or every later write hangs.
    tester, token = store.register("bob", engine_quota=1)
    assert store.authenticate(token) == tester


def test_reopening_an_existing_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "testers.db"
    first = TesterStore(db)
    tester, token = first.register("ada", engine_quota=1)
    first.close()

    with TesterStore(db) as reopened:
        assert reopened.authenticate(token) == tester
