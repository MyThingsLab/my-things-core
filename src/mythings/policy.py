from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
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


# A "large product repo" (many subtrees, one owner per subtree) needs one more
# primitive: a diff spanning two owners' subtrees is a different class of risk
# than a same-owner diff and should escalate rather than silently proceed.
# `owners` maps a subtree's root path to an owner name; the map itself lives
# in the target repo (e.g. a CODEOWNERS-style file a caller parses into this
# shape) -- core only holds the deterministic boundary check, not the file
# format or where it's read from, since no shipped tool needs that yet.


def subtree_owner(path: str, owners: dict[str, str]) -> str | None:
    # Deepest-matching subtree wins (like CODEOWNERS), matched by whole path
    # segment so "data" never matches "database/x.py". A path under no
    # declared subtree is unowned (None), not an error -- most repos have
    # shared root files (README, CI config) nobody subtree owns exclusively.
    parts = PurePosixPath(path).parts
    best: tuple[int, str] | None = None
    for subtree, owner in owners.items():
        subtree_parts = PurePosixPath(subtree).parts
        if parts[: len(subtree_parts)] == subtree_parts:
            if best is None or len(subtree_parts) > best[0]:
                best = (len(subtree_parts), owner)
    return best[1] if best else None


def ownership_boundary(paths: list[str], owners: dict[str, str]) -> PolicyResult:
    # Escalate, don't hard-deny: a genuine cross-owner change (a shared
    # interface, a deliberate refactor) is real work a human may want to let
    # through, not a permanent block -- ASK already has a real resolution
    # path via my-guard's ask channel, so reusing it here is the "explicit
    # override" the design calls for, not a new bypass mechanism. Unowned
    # paths never count toward the touched-owner set: mixing one owner's
    # subtree with shared root files is routine, not a boundary crossing.
    touched = {owner for path in paths if (owner := subtree_owner(path, owners)) is not None}
    if len(touched) <= 1:
        return ALLOW
    names = ", ".join(sorted(touched))
    return PolicyResult(
        Decision.ASK,
        reason=f"diff spans {len(touched)} owners' subtrees ({names}) — needs a human to confirm",
        rule="ownership-boundary",
    )
