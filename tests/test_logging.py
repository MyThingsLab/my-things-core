import json
import logging
from pathlib import Path

from mythings.logging import configure, log


def test_json_sink_writes_one_object_per_line(tmp_path: Path) -> None:
    logger = configure("my-guard", json_path=tmp_path / "run.jsonl", console=False)
    log(logger, logging.INFO, "denied a push", rule="protect_main")
    log(logger, logging.ERROR, "engine call failed")

    lines = (tmp_path / "run.jsonl").read_text().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["tool"] == "my-guard"
    assert first["level"] == "info"
    assert first["msg"] == "denied a push"
    assert first["data"] == {"rule": "protect_main"}

    second = json.loads(lines[1])
    assert second["level"] == "error"
    assert "data" not in second


def test_json_sink_creates_parent_dirs(tmp_path: Path) -> None:
    logger = configure("t", json_path=tmp_path / "nested" / "deep" / "run.jsonl", console=False)
    log(logger, logging.INFO, "hello")
    assert (tmp_path / "nested" / "deep" / "run.jsonl").exists()


def test_console_sink_is_human_readable(capsys) -> None:
    logger = configure("my-tester", console=True)
    log(logger, logging.WARNING, "retrying", attempt=2)

    err = capsys.readouterr().err
    assert "my-tester" in err
    assert "retrying" in err
    assert "attempt=2" in err


def test_level_filters_below_threshold(tmp_path: Path) -> None:
    logger = configure("t", level=logging.WARNING, json_path=tmp_path / "run.jsonl", console=False)
    log(logger, logging.INFO, "ignored")
    log(logger, logging.WARNING, "kept")

    lines = (tmp_path / "run.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["msg"] == "kept"


def test_reconfigure_replaces_handlers(tmp_path: Path) -> None:
    configure("t", json_path=tmp_path / "a.jsonl", console=False)
    logger = configure("t", json_path=tmp_path / "b.jsonl", console=False)
    log(logger, logging.INFO, "only in b")

    assert (tmp_path / "a.jsonl").read_text() == ""
    assert (tmp_path / "b.jsonl").read_text().strip() != ""
