import json

from mythings.engine import ClaudeCLIEngine, Engine, EngineRequest, EngineResult, NoopEngine


class _FakeRunner:
    def __init__(self, reply: str) -> None:
        self.calls: list[list[str]] = []
        self.reply = reply

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self.reply


def test_claude_cli_engine_builds_argv_and_extracts_result_text() -> None:
    fake = _FakeRunner(json.dumps({"result": "ship it", "is_error": False}))
    eng = ClaudeCLIEngine(model="claude-sonnet-5", runner=fake)

    result = eng.run(EngineRequest(prompt="pick one", system="be terse"))

    assert result == EngineResult(text="ship it", data={"result": "ship it", "is_error": False})
    argv = fake.calls[0]
    assert argv[:4] == ["-p", "--output-format", "json", "--tools"]
    assert argv[4] == ""  # tools disabled: judgment only, no side effects
    assert "--system-prompt" in argv and "be terse" in argv
    assert "--model" in argv and "claude-sonnet-5" in argv
    assert argv[-1] == "pick one"  # prompt passed last, positionally


def test_claude_cli_engine_omits_optional_flags_when_unset() -> None:
    fake = _FakeRunner(json.dumps({"result": "ok"}))
    ClaudeCLIEngine(runner=fake).run(EngineRequest(prompt="x"))

    argv = fake.calls[0]
    assert "--system-prompt" not in argv
    assert "--model" not in argv


def test_claude_cli_engine_degrades_to_empty_on_nonzero_exit() -> None:
    # The default runner returns "" on a nonzero exit; assert that a blank
    # reply degrades exactly like NoopEngine's, not an exception.
    eng = ClaudeCLIEngine(runner=lambda argv: "")
    assert eng.run(EngineRequest(prompt="x")) == EngineResult(text="", data={})


def test_claude_cli_engine_degrades_to_empty_on_malformed_json() -> None:
    eng = ClaudeCLIEngine(runner=lambda argv: "not json")
    assert eng.run(EngineRequest(prompt="x")) == EngineResult(text="", data={})


def test_claude_cli_engine_degrades_to_empty_when_is_error() -> None:
    fake = _FakeRunner(json.dumps({"result": "partial garbage", "is_error": True}))
    result = ClaudeCLIEngine(runner=fake).run(EngineRequest(prompt="x"))
    assert result.text == ""


def test_claude_cli_engine_protocol_compliance() -> None:
    assert isinstance(ClaudeCLIEngine(runner=lambda argv: ""), Engine)


def test_noop_is_deterministic_and_takes_no_tokens() -> None:
    eng = NoopEngine(reply="ok")
    req = EngineRequest(prompt="do the thing", system="be terse")
    first = eng.run(req)
    second = eng.run(req)
    assert first == second
    assert first == EngineResult(text="ok", data={"echo": "do the thing"})


def test_noop_default_reply_is_empty() -> None:
    assert NoopEngine().run(EngineRequest(prompt="x")).text == ""


def test_engine_protocol_is_structural() -> None:
    assert isinstance(NoopEngine(), Engine)
    assert not isinstance(object(), Engine)
