from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


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
