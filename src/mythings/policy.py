from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Action:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str = ""
    rule: str = ""

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.DENY

    def under(self, *, unattended: bool) -> Decision:
        if unattended and self.decision is Decision.ASK:
            return Decision.DENY
        return self.decision


@runtime_checkable
class Policy(Protocol):
    def evaluate(self, action: Action) -> PolicyResult: ...


ALLOW = PolicyResult(Decision.ALLOW)
