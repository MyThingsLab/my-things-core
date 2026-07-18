import base64
import json

import mythings.engine as engine_module
from mythings.engine import (
    CachingEngine,
    ClaudeCLIEngine,
    Engine,
    EngineRequest,
    EngineResult,
    MeteredEngine,
    NoopEngine,
    TieredEngine,
)


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


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_default_claude_runner_surfaces_stderr_on_nonzero_exit(monkeypatch) -> None:
    # Regression for #110: a nonzero exit used to collapse to "", making a
    # directory-triggered CLI failure indistinguishable from "the model
    # answered with nothing". The default runner must now surface stderr and
    # the returncode instead of discarding them.
    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        lambda *a, **k: _FakeCompletedProcess(1, stdout="", stderr="permission denied"),
    )
    raw = engine_module._claude(["-p", "x"])
    envelope = json.loads(raw)
    assert envelope == {
        "type": "result",
        "is_error": True,
        "returncode": 1,
        "stderr": "permission denied",
    }


def test_default_claude_runner_passes_stdout_through_on_success(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        lambda *a, **k: _FakeCompletedProcess(0, stdout='{"result": "ok"}'),
    )
    assert engine_module._claude(["-p", "x"]) == '{"result": "ok"}'


def test_claude_cli_engine_degrades_but_records_stderr_on_nonzero_exit() -> None:
    # End-to-end through ClaudeCLIEngine: text still degrades to "" (same
    # contract as every other failure), but data now carries what actually
    # went wrong instead of being empty.
    fake_raw = json.dumps(
        {"type": "result", "is_error": True, "returncode": 1, "stderr": "permission denied"}
    )
    eng = ClaudeCLIEngine(runner=lambda argv: fake_raw)
    result = eng.run(EngineRequest(prompt="x"))
    assert result.text == ""
    assert result.data == {
        "type": "result",
        "is_error": True,
        "returncode": 1,
        "stderr": "permission denied",
    }


def test_default_claude_stream_runner_surfaces_stderr_on_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_module.subprocess,
        "run",
        lambda *a, **k: _FakeCompletedProcess(1, stdout="", stderr="permission denied"),
    )
    raw = engine_module._claude_stream(["-p", "x"], "{}")
    envelope = json.loads(raw)
    assert envelope["is_error"] is True
    assert envelope["stderr"] == "permission denied"


def test_claude_cli_engine_multimodal_records_stderr_on_nonzero_exit() -> None:
    fake_raw = json.dumps(
        {"type": "result", "is_error": True, "returncode": 1, "stderr": "permission denied"}
    )
    eng = ClaudeCLIEngine(runner=lambda argv: "", stream_runner=lambda argv, stdin: fake_raw)
    result = eng.run(EngineRequest(prompt="x", images=(b"img",)))
    assert result.text == ""
    assert result.data["stderr"] == "permission denied"


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


class _FakeStreamRunner:
    def __init__(self, reply: str) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.reply = reply

    def __call__(self, argv: list[str], stdin_text: str) -> str:
        self.calls.append((argv, stdin_text))
        return self.reply


def _stream_json_reply(**result_fields: object) -> str:
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}),
        json.dumps({"type": "result", **result_fields}),
    ]
    return "\n".join(lines) + "\n"


def test_claude_cli_engine_switches_to_stream_json_when_images_present() -> None:
    text_runner = _FakeRunner("should never be called")
    stream = _FakeStreamRunner(_stream_json_reply(result="a red circle", is_error=False))
    eng = ClaudeCLIEngine(runner=text_runner, stream_runner=stream)

    result = eng.run(
        EngineRequest(prompt="describe this", system="be terse", images=(b"\x89PNG...",))
    )

    assert result == EngineResult(
        text="a red circle", data={"type": "result", "result": "a red circle", "is_error": False}
    )
    assert not text_runner.calls  # the text path's Runner is never invoked
    argv, stdin_text = stream.calls[0]
    assert "--input-format" in argv and "stream-json" in argv
    assert "--output-format" in argv and "stream-json" in argv
    assert "--tools=" in argv
    assert "--system-prompt" in argv and "be terse" in argv
    message = json.loads(stdin_text)
    content = message["message"]["content"]
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["media_type"] == "image/png"
    decoded = base64.b64decode(content[1]["source"]["data"])
    assert decoded == b"\x89PNG..."


def test_claude_cli_engine_multimodal_degrades_to_empty_on_is_error() -> None:
    stream = _FakeStreamRunner(_stream_json_reply(result="partial", is_error=True))
    eng = ClaudeCLIEngine(runner=_FakeRunner(""), stream_runner=stream)
    result = eng.run(EngineRequest(prompt="x", images=(b"img",)))
    assert result.text == ""


def test_claude_cli_engine_multimodal_ignores_non_result_lines() -> None:
    stream = _FakeStreamRunner(_stream_json_reply(result="ok", is_error=False))
    eng = ClaudeCLIEngine(runner=_FakeRunner(""), stream_runner=stream)
    result = eng.run(EngineRequest(prompt="x", images=(b"img",)))
    assert result.text == "ok"


def test_claude_cli_engine_multimodal_degrades_on_malformed_stream() -> None:
    stream = _FakeStreamRunner("not json at all")
    eng = ClaudeCLIEngine(runner=_FakeRunner(""), stream_runner=stream)
    result = eng.run(EngineRequest(prompt="x", images=(b"img",)))
    assert result == EngineResult(text="", data={})


def test_claude_cli_engine_multiple_images_all_attached() -> None:
    stream = _FakeStreamRunner(_stream_json_reply(result="ok", is_error=False))
    eng = ClaudeCLIEngine(runner=_FakeRunner(""), stream_runner=stream)
    eng.run(EngineRequest(prompt="x", images=(b"one", b"two")))
    _, stdin_text = stream.calls[0]
    content = json.loads(stdin_text)["message"]["content"]
    images = [c for c in content if c["type"] == "image"]
    assert len(images) == 2
    assert base64.b64decode(images[0]["source"]["data"]) == b"one"
    assert base64.b64decode(images[1]["source"]["data"]) == b"two"


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


def test_caching_engine_distinguishes_requests_by_image(tmp_path):
    from mythings.engine import CachingEngine

    delegate = _CountingEngine(EngineResult(text="x"))
    eng = CachingEngine(delegate, tmp_path / "c")
    eng.run(EngineRequest(prompt="describe", images=(b"one",)))
    eng.run(EngineRequest(prompt="describe", images=(b"two",)))
    eng.run(EngineRequest(prompt="describe", images=(b"one",)))  # repeat -> cache hit

    assert len(delegate.calls) == 2


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


# --- the engine-boundary contract -------------------------------------------
#
# The one non-deterministic seam is exactly where a silent degradation cannot
# be caught by any tool's own NoopEngine-based tests (the context-drop and
# fence-wrapping defects both shipped through green CI). These tests pin the
# boundary's contract for every backend in this module.

_CANARY = "CATALOG-CANARY-9f31"


def _all_backends(tmp_path):
    fake = _FakeRunner(json.dumps({"result": "ok"}))
    return [
        NoopEngine("ok"),
        ClaudeCLIEngine(runner=fake),
        CachingEngine(NoopEngine("ok"), tmp_path / "cache"),
        MeteredEngine(NoopEngine("ok"), _FakeLedger(), tool="t"),
    ]


def test_every_backend_satisfies_the_protocol_and_returns_text(tmp_path) -> None:
    for backend in _all_backends(tmp_path):
        assert isinstance(backend, Engine)
        result = backend.run(EngineRequest(prompt="x", context={"k": "v"}))
        assert isinstance(result, EngineResult)
        assert isinstance(result.text, str)


def test_context_is_never_transmitted_to_the_model() -> None:
    # EngineRequest.context is cache-key/audit metadata. Grounding a call on
    # it is the my-guide.wish() bug: the tool's NoopEngine tests pass while
    # the real model never sees the catalog. Pin the contract: nothing from
    # context may reach the CLI's argv.
    fake = _FakeRunner(json.dumps({"result": "ok"}))
    ClaudeCLIEngine(runner=fake).run(
        EngineRequest(prompt="route this wish", context={"catalog": _CANARY})
    )
    argv = fake.calls[0]
    assert all(_CANARY not in token for token in argv)
    assert all("catalog" not in token for token in argv)


def test_context_still_distinguishes_cache_entries(tmp_path) -> None:
    # The flip side of the same contract: context is part of CachingEngine's
    # key, so two calls differing only in context are cached separately.
    cache = CachingEngine(NoopEngine("ok"), tmp_path / "cache")
    cache.run(EngineRequest(prompt="p", context={"n": 1}))
    cache.run(EngineRequest(prompt="p", context={"n": 2}))
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


# --- MeteredEngine -----------------------------------------------------------


class _FakeLedger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, **fields) -> None:
        self.entries.append(fields)


def test_metered_engine_ledgers_cost_from_the_cli_envelope() -> None:
    fake = _FakeRunner(json.dumps({"result": "ok", "total_cost_usd": 0.0421}))
    ledger = _FakeLedger()
    metered = MeteredEngine(
        ClaudeCLIEngine(runner=fake), ledger, tool="mydocs", model="claude-haiku-4-5"
    )

    result = metered.run(EngineRequest(prompt="gloss this page"))

    assert result.text == "ok"
    (entry,) = ledger.entries
    assert entry["tool"] == "mydocs"
    assert entry["kind"] == "engine_usage"
    assert entry["outcome"] == "success"
    assert entry["cost_usd"] == 0.0421
    assert entry["model"] == "claude-haiku-4-5"
    assert entry["prompt_chars"] == len("gloss this page")
    assert entry["reply_chars"] == len("ok")


def test_metered_engine_records_empty_outcome_with_zero_cost() -> None:
    ledger = _FakeLedger()
    MeteredEngine(NoopEngine(""), ledger, tool="t").run(EngineRequest(prompt="x"))
    (entry,) = ledger.entries
    assert entry["outcome"] == "empty"
    assert entry["cost_usd"] == 0.0


def test_metered_engine_passes_the_request_through_unchanged() -> None:
    seen: list[EngineRequest] = []

    class Spy:
        def run(self, request: EngineRequest) -> EngineResult:
            seen.append(request)
            return EngineResult(text="ok")

    request = EngineRequest(prompt="p", system="s", context={"k": "v"})
    MeteredEngine(Spy(), _FakeLedger(), tool="t").run(request)
    assert seen == [request]


def test_cache_over_meter_bills_and_meters_once(tmp_path) -> None:
    # The documented composition: CachingEngine(MeteredEngine(backend)). The
    # second identical request is a cache hit -- it bills nothing, so it must
    # meter nothing.
    fake = _FakeRunner(json.dumps({"result": "ok", "total_cost_usd": 0.05}))
    ledger = _FakeLedger()
    engine = CachingEngine(
        MeteredEngine(ClaudeCLIEngine(runner=fake), ledger, tool="t"), tmp_path / "cache"
    )

    engine.run(EngineRequest(prompt="same"))
    engine.run(EngineRequest(prompt="same"))

    assert len(fake.calls) == 1
    assert len(ledger.entries) == 1


class _NamedEngine:
    # A fake tier: returns a scripted result and records whether it ran, so a
    # skipped/never-reached tier is observable as "never called".
    def __init__(self, result: EngineResult) -> None:
        self.result = result
        self.calls = 0

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls += 1
        return self.result


def test_tiered_engine_returns_first_accepted_tier() -> None:
    cheap = _NamedEngine(EngineResult(text=""))
    expensive = _NamedEngine(EngineResult(text="real answer"))
    tiered = TieredEngine([("cheap", cheap), ("expensive", expensive)])

    result = tiered.run(EngineRequest(prompt="p"))

    assert result.text == "real answer"
    assert cheap.calls == 1
    assert expensive.calls == 1


def test_tiered_engine_stops_at_the_first_accepting_tier() -> None:
    cheap = _NamedEngine(EngineResult(text="good enough"))
    expensive = _NamedEngine(EngineResult(text="never reached"))
    tiered = TieredEngine([("cheap", cheap), ("expensive", expensive)])

    result = tiered.run(EngineRequest(prompt="p"))

    assert result.text == "good enough"
    assert expensive.calls == 0  # cheap tier already satisfied accept()


def test_tiered_engine_skips_named_tiers() -> None:
    cheap = _NamedEngine(EngineResult(text="cheap answer"))
    expensive = _NamedEngine(EngineResult(text="expensive answer"))
    tiered = TieredEngine([("cheap", cheap), ("expensive", expensive)], skip={"cheap"})

    result = tiered.run(EngineRequest(prompt="p"))

    assert result.text == "expensive answer"
    assert cheap.calls == 0


def test_tiered_engine_uses_a_custom_accept_callback() -> None:
    tier_a = _NamedEngine(EngineResult(text="short"))
    tier_b = _NamedEngine(EngineResult(text="long enough answer"))
    tiered = TieredEngine(
        [("a", tier_a), ("b", tier_b)],
        accept=lambda r: len(r.text) > 10,
    )

    result = tiered.run(EngineRequest(prompt="p"))

    assert result.text == "long enough answer"


def test_tiered_engine_degrades_to_the_last_tier_when_none_accept() -> None:
    tier_a = _NamedEngine(EngineResult(text=""))
    tier_b = _NamedEngine(EngineResult(text=""))
    tiered = TieredEngine([("a", tier_a), ("b", tier_b)])

    result = tiered.run(EngineRequest(prompt="p"))

    assert result.text == ""
    assert tier_a.calls == 1
    assert tier_b.calls == 1


def test_tiered_engine_returns_empty_when_every_tier_is_skipped() -> None:
    tier_a = _NamedEngine(EngineResult(text="unreachable"))
    tiered = TieredEngine([("a", tier_a)], skip={"a"})

    result = tiered.run(EngineRequest(prompt="p"))

    assert result == EngineResult(text="")
    assert tier_a.calls == 0


def test_tiered_engine_protocol_compliance() -> None:
    assert isinstance(TieredEngine([]), Engine)


def test_tiered_engine_composes_with_caching_and_metering(tmp_path) -> None:
    # The doc's motivating composition: a caching/metered expensive tier
    # behind a cheap deterministic one, same style as CachingEngine(
    # MeteredEngine(ClaudeCLIEngine(...))).
    cheap = _NamedEngine(EngineResult(text=""))
    expensive = CachingEngine(
        _NamedEngine(EngineResult(text="from claude")), tmp_path / "cache"
    )
    tiered = TieredEngine([("cheap", cheap), ("expensive", expensive)])

    first = tiered.run(EngineRequest(prompt="same"))
    second = tiered.run(EngineRequest(prompt="same"))

    assert first.text == second.text == "from claude"
