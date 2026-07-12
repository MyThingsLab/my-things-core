from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# A Runner takes the argv after `claude` and returns raw stdout. The default
# shells out; tests inject a fake so the `claude` process is the only thing
# mocked (same pattern as github.Runner/_gh).
Runner = Callable[[list[str]], str]

# A StreamRunner is the image-path's Runner equivalent: argv plus the stdin
# text to pipe in (a single stream-json message line), returning raw stdout.
# Separate from Runner rather than widening it, so every existing `runner=`
# fake (every caller before images existed) keeps working unchanged.
StreamRunner = Callable[[list[str], str], str]


@dataclass(frozen=True)
class EngineRequest:
    prompt: str
    system: str = ""
    # Cache-key / audit metadata ONLY -- no backend transmits it to the model.
    # Anything the model must actually see (grounding, candidate lists, a
    # catalog to choose from) goes in `prompt`. See docs/ARCHITECTURE.md.
    context: dict[str, Any] = field(default_factory=dict)
    # PNG-encoded image bytes to attach (e.g. a cropped PDF figure/equation
    # region) -- empty for every caller that predates this field. Non-empty
    # switches ClaudeCLIEngine to the stream-json wire format (see below);
    # NoopEngine and every other backend just ignores it.
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class EngineResult:
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Engine(Protocol):
    def run(self, request: EngineRequest) -> EngineResult: ...


class NoopEngine:
    def __init__(self, reply: str = "") -> None:
        self._reply = reply

    def run(self, request: EngineRequest) -> EngineResult:
        return EngineResult(text=self._reply, data={"echo": request.prompt})


def _claude(argv: list[str]) -> str:
    proc = subprocess.run(["claude", *argv], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _claude_stream(argv: list[str], stdin_text: str) -> str:
    proc = subprocess.run(
        ["claude", *argv], input=stdin_text, capture_output=True, text=True
    )
    return proc.stdout if proc.returncode == 0 else ""


# Models routinely wrap JSON replies in a ```json fence despite a system
# prompt saying not to (verified against claude-haiku-4-5 at low effort).
# Strip one whole-string fence here so every consumer's json.loads(result.text)
# succeeds regardless of a given model's compliance with that instruction.
_FENCE_RE = re.compile(r"^```[\w+-]*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1) if match else text


class ClaudeCLIEngine:
    # Shells out to the Claude Code CLI in headless print mode instead of an
    # SDK: no new dependency, and it reuses whatever `claude` auth is already
    # configured on the machine. Tools are disabled (--tools=) — this seam
    # returns judgment only, never a side effect; those stay behind Policy.
    # Never raises: a CLI failure or unparsable reply degrades to
    # EngineResult(text="", ...), same contract shape as NoopEngine's empty
    # reply, so every tool's existing "--summarize degrades gracefully"
    # handling covers this backend for free.
    def __init__(
        self,
        *,
        model: str | None = None,
        runner: Runner = _claude,
        stream_runner: StreamRunner = _claude_stream,
    ) -> None:
        self._model = model
        self._run = runner
        self._run_stream = stream_runner

    def run(self, request: EngineRequest) -> EngineResult:
        if request.images:
            return self._run_multimodal(request)

        # --tools as two argv tokens ("--tools", "") makes the CLI's variadic
        # tools-list parser keep consuming the next token too when nothing
        # else with a leading "-" follows (e.g. no --system-prompt) — it
        # swallows the positional prompt itself. A single "--tools=" token
        # disables tools without that ambiguity, verified against the real
        # CLI (2.1.202).
        argv = ["-p", "--output-format", "json", "--tools="]
        if request.system:
            argv += ["--system-prompt", request.system]
        if self._model:
            argv += ["--model", self._model]
        argv.append(request.prompt)

        raw = self._run(argv)
        try:
            obj = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            obj = {}
        text = "" if obj.get("is_error") else _strip_code_fence(obj.get("result", ""))
        return EngineResult(text=text, data=obj)

    def _run_multimodal(self, request: EngineRequest) -> EngineResult:
        # `-p` alone has no way to attach an image to the positional prompt --
        # verified against the real CLI (2.1.207): stream-json input/output is
        # the one documented path that accepts an Anthropic-style content-block
        # message (text + base64 image) over stdin. Same --tools= disable, so
        # this stays judgment-only like the text path.
        argv = [
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--tools=",
        ]
        if request.system:
            argv += ["--system-prompt", request.system]
        if self._model:
            argv += ["--model", self._model]

        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for image in request.images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        stdin_text = (
            json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        )

        raw = self._run_stream(argv, stdin_text)
        obj = self._last_result_line(raw)
        text = "" if obj.get("is_error") else _strip_code_fence(obj.get("result", ""))
        return EngineResult(text=text, data=obj)

    @staticmethod
    def _last_result_line(raw: str) -> dict[str, Any]:
        # stream-json output is one JSON object per line (system/assistant/
        # result/...); the `result` line carries the same result/is_error
        # shape the text path parses from --output-format json.
        result: dict[str, Any] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "result":
                result = obj
        return result


class CachingEngine:
    # Wraps any Engine in a content-addressed disk cache. A billed Claude call
    # is a pure function of (system, prompt, context, model): ClaudeCLIEngine
    # disables tools and returns judgment only, no side effects. So an identical
    # request never needs to be paid for twice -- re-defining a term, re-briefing
    # a topic, or resuming a crashed fleet cycle all become free on a cache hit.
    #
    # Opt-in and inert like corpus.cached_extractor: constructed explicitly with
    # a delegate and a directory, touches no disk until run() is called, and adds
    # no dependency (hashlib + json, stdlib).
    #
    # `tag` namespaces the cache -- pass the model name (or any version marker)
    # so switching models does not serve one model's answer for another's request.
    def __init__(self, delegate: Engine, cache_dir: str | Path, *, tag: str = "") -> None:
        self._delegate = delegate
        self._dir = Path(cache_dir)
        self._tag = tag

    def _key(self, request: EngineRequest) -> str:
        payload = json.dumps(
            {
                "tag": self._tag,
                "system": request.system,
                "prompt": request.prompt,
                "context": request.context,
                # Images are typically kilobytes; hash each rather than
                # inlining the bytes, same reasoning as corpus.cached_extractor
                # keying on (size, mtime) instead of file content.
                "images": [hashlib.sha256(image).hexdigest() for image in request.images],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def run(self, request: EngineRequest) -> EngineResult:
        entry = self._dir / (self._key(request) + ".json")
        try:
            cached = json.loads(entry.read_text(encoding="utf-8"))
            return EngineResult(text=cached["text"], data=cached["data"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        result = self._delegate.run(request)
        # Never cache a failure or an empty reply: an errored/degraded call
        # returns text="" (see ClaudeCLIEngine), and caching that would poison
        # every future identical request with a transient failure. Only a real,
        # non-empty answer is worth remembering.
        if result.text and not result.data.get("is_error"):
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = entry.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"text": result.text, "data": result.data}), encoding="utf-8")
            tmp.replace(entry)
        return result


class MeteredEngine:
    # Wraps any Engine and appends one kind=engine_usage entry per run() to a
    # Ledger, so per-tool Engine spend is reconstructable from the ledger the
    # way dispatched-worker spend already is. ClaudeCLIEngine's CLI reply
    # carries total_cost_usd in its JSON envelope; until now every consumer
    # dropped it on the floor, so the fleet's per-call spend was unknowable.
    #
    # Composition order matters: wrap the billed backend directly and put the
    # cache outside -- CachingEngine(MeteredEngine(ClaudeCLIEngine(...), ...))
    # -- so a cache hit, which bills nothing, meters nothing.
    def __init__(self, delegate: Engine, ledger: Any, *, tool: str, model: str = "") -> None:
        # `ledger` is any object with Ledger's record(**fields) shape; typed
        # loosely to keep this module import-free of mythings.ledger.
        self._delegate = delegate
        self._ledger = ledger
        self._tool = tool
        self._model = model

    def run(self, request: EngineRequest) -> EngineResult:
        started = time.monotonic()
        result = self._delegate.run(request)
        cost = float(result.data.get("total_cost_usd") or 0.0)
        self._ledger.record(
            tool=self._tool,
            kind="engine_usage",
            outcome="success" if result.text else "empty",
            detail=f"engine call: ${cost:.4f} ({self._model or 'default model'})",
            cost_usd=cost,
            model=self._model,
            duration_s=round(time.monotonic() - started, 3),
            prompt_chars=len(request.prompt),
            reply_chars=len(result.text),
        )
        return result
