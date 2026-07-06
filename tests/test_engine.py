from mythings.engine import Engine, EngineRequest, EngineResult, NoopEngine


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
