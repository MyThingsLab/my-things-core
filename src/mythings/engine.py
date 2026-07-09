from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# A Runner takes the argv after `claude` and returns raw stdout. The default
# shells out; tests inject a fake so the `claude` process is the only thing
# mocked (same pattern as github.Runner/_gh).
Runner = Callable[[list[str]], str]


@dataclass(frozen=True)
class EngineRequest:
    prompt: str
    system: str = ""
    context: dict[str, Any] = field(default_factory=dict)


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
    def __init__(self, *, model: str | None = None, runner: Runner = _claude) -> None:
        self._model = model
        self._run = runner

    def run(self, request: EngineRequest) -> EngineResult:
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
