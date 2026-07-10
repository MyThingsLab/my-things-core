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
    assert argv[:4] == ["-p", "--output-format", "json", "--tools="]  # one token: tools disabled
    assert "--system-prompt" in argv and "be terse" in argv
    assert "--model" in argv and "claude-sonnet-5" in argv
    assert argv[-1] == "pick one"  # prompt passed last, positionally


def test_claude_cli_engine_omits_optional_flags_when_unset() -> None:
    fake = _FakeRunner(json.dumps({"result": "ok"}))
    ClaudeCLIEngine(runner=fake).run(EngineRequest(prompt="x"))

    argv = fake.calls[0]
    assert "--system-prompt" not in argv
    assert "--model" not in argv
    # Regression: with no --system-prompt/--model following, "--tools" as two
    # tokens ("--tools", "") let the CLI's variadic parser swallow this
    # positional prompt too. Must stay the single joined "--tools=" token.
    assert "--tools=" in argv
    assert argv[-1] == "x"  # prompt still positional-last, not swallowed


def test_claude_cli_engine_degrades_to_empty_on_nonzero_exit() -> None:
    # The default runner returns "" on a nonzero exit; assert that a blank
    # reply degrades exactly like NoopEngine's, not an exception.
    eng = ClaudeCLIEngine(runner=lambda argv: "")
    assert eng.run(EngineRequest(prompt="x")) == EngineResult(text="", data={})


def test_claude_cli_engine_degrades_to_empty_on_malformed_json() -> None:
    eng = ClaudeCLIEngine(runner=lambda argv: "not json")
    assert eng.run(EngineRequest(prompt="x")) == EngineResult(text="", data={})


def test_claude_cli_engine_strips_markdown_json_fence_from_result() -> None:
    # claude-haiku-4-5 at low effort wraps JSON replies in a ```json fence
    # despite a system prompt saying not to; downstream json.loads(result.text)
    # must still succeed.
    fenced = '```json\n{"brief": "ok"}\n```'
    fake = _FakeRunner(json.dumps({"result": fenced, "is_error": False}))
    result = ClaudeCLIEngine(runner=fake).run(EngineRequest(prompt="x"))
    assert result.text == '{"brief": "ok"}'
    assert json.loads(result.text) == {"brief": "ok"}


def test_claude_cli_engine_leaves_unfenced_result_untouched() -> None:
    fake = _FakeRunner(json.dumps({"result": "plain text", "is_error": False}))
    result = ClaudeCLIEngine(runner=fake).run(EngineRequest(prompt="x"))
    assert result.text == "plain text"


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


class _CountingEngine:
    # A delegate that records every call and returns a scripted result, so a
    # cache hit is observable as "the delegate was not called again".
    def __init__(self, result: EngineResult) -> None:
        self.result = result
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return self.result


def test_caching_engine_serves_a_repeat_request_from_disk(tmp_path):
    from mythings.engine import CachingEngine

    delegate = _CountingEngine(EngineResult(text="a definition", data={"is_error": False}))
    eng = CachingEngine(delegate, tmp_path / "engine-cache")
    req = EngineRequest(prompt="define EM", system="be precise")

    first = eng.run(req)
    second = eng.run(req)

    assert first == second
    assert first.text == "a definition"
    assert len(delegate.calls) == 1  # the second run never reached the delegate


def test_caching_engine_distinguishes_requests_by_content(tmp_path):
    from mythings.engine import CachingEngine

    delegate = _CountingEngine(EngineResult(text="x"))
    eng = CachingEngine(delegate, tmp_path / "c")
    eng.run(EngineRequest(prompt="define EM"))
    eng.run(EngineRequest(prompt="define PCA"))
    eng.run(EngineRequest(prompt="define EM", system="different system"))

    assert len(delegate.calls) == 3  # each distinct request is billed once


def test_caching_engine_isolates_by_tag(tmp_path):
    # The same prompt on two models must not share an answer. Same dir, different
    # tag => a miss, so a model switch never serves the other model's reply.
    from mythings.engine import CachingEngine

    cache = tmp_path / "shared"
    haiku = _CountingEngine(EngineResult(text="haiku says"))
    opus = _CountingEngine(EngineResult(text="opus says"))
    req = EngineRequest(prompt="define EM")

    assert CachingEngine(haiku, cache, tag="haiku").run(req).text == "haiku says"
    assert CachingEngine(opus, cache, tag="opus").run(req).text == "opus says"
    # And each is independently cached.
    assert CachingEngine(haiku, cache, tag="haiku").run(req).text == "haiku says"
    assert len(haiku.calls) == 1


def test_caching_engine_never_caches_a_failure(tmp_path):
    from mythings.engine import CachingEngine

    delegate = _CountingEngine(EngineResult(text="", data={"is_error": True}))
    eng = CachingEngine(delegate, tmp_path / "c")
    req = EngineRequest(prompt="define EM")

    eng.run(req)
    eng.run(req)
    # A transient failure must not poison the cache: the delegate is retried.
    assert len(delegate.calls) == 2
    assert not (tmp_path / "c").exists() or not list((tmp_path / "c").glob("*.json"))


def test_caching_engine_never_caches_an_empty_reply(tmp_path):
    from mythings.engine import CachingEngine

    delegate = _CountingEngine(EngineResult(text="", data={}))
    eng = CachingEngine(delegate, tmp_path / "c")
    req = EngineRequest(prompt="define EM")
    eng.run(req)
    eng.run(req)
    assert len(delegate.calls) == 2


def test_caching_engine_is_inert_until_run(tmp_path):
    from mythings.engine import CachingEngine

    cache = tmp_path / "never"
    CachingEngine(_CountingEngine(EngineResult(text="x")), cache)
    assert not cache.exists()


def test_caching_engine_leaves_no_temp_file(tmp_path):
    from mythings.engine import CachingEngine

    cache = tmp_path / "c"
    CachingEngine(_CountingEngine(EngineResult(text="x", data={})), cache).run(
        EngineRequest(prompt="p")
    )
    assert [p.suffix for p in cache.iterdir()] == [".json"]
