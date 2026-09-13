from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class LedgerEntry:
    tool: str
    kind: str
    outcome: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_utc_now)

    @property
    def prompt_tokens(self) -> int:
        return int(self.data.get("prompt_tokens", 0) or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.data.get("completion_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        if "total_tokens" in self.data:
            return int(self.data["total_tokens"] or 0)
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return float(self.data.get("cost_usd", 0.0) or 0.0)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> LedgerEntry:
        obj = json.loads(line)
        return cls(
            tool=obj["tool"],
            kind=obj["kind"],
            outcome=obj["outcome"],
            detail=obj.get("detail", ""),
            data=obj.get("data", {}),
            ts=obj.get("ts", _utc_now()),
        )


@dataclass
class Checkpoint:
    """Durable state summary for a candidate issue across dispatch attempts."""

    candidate_id: str
    last_outcome: str
    attempt_count: int
    total_spend_usd: float
    total_tokens: int
    target_symbols: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    blocker_reason: str | None = None
    latest_ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "last_outcome": self.last_outcome,
            "attempt_count": self.attempt_count,
            "total_spend_usd": round(self.total_spend_usd, 4),
            "total_tokens": self.total_tokens,
            "target_symbols": self.target_symbols,
            "failed_tests": self.failed_tests,
            "blocker_reason": self.blocker_reason,
            "latest_ts": self.latest_ts,
        }


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_json() + "\n")
        return entry

    def record(
        self,
        tool: str,
        kind: str,
        outcome: str,
        detail: str = "",
        **data: Any,
    ) -> LedgerEntry:
        entry = LedgerEntry(tool=tool, kind=kind, outcome=outcome, detail=detail, data=data)
        return self.append(entry)

    def __iter__(self) -> Iterator[LedgerEntry]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield LedgerEntry.from_json(line)

    def read(self, *, tool: str | None = None, kind: str | None = None) -> list[LedgerEntry]:
        return [
            e
            for e in self
            if (tool is None or e.tool == tool) and (kind is None or e.kind == kind)
        ]

    def get_checkpoint(self, candidate_id: str) -> Checkpoint | None:
        """Synthesize a token-efficient checkpoint for a candidate issue."""
        entries = [
            e
            for e in self
            if e.data.get("candidate") == candidate_id or e.data.get("candidate_id") == candidate_id
        ]
        if not entries:
            return None

        last_entry = entries[-1]
        attempt_count = sum(1 for e in entries if e.kind in ("dispatch", "attempt"))
        total_spend = sum(e.cost_usd for e in entries)
        total_toks = sum(e.total_tokens for e in entries)

        symbols: set[str] = set()
        failed_tests: set[str] = set()
        blocker: str | None = None

        for e in entries:
            syms = e.data.get("target_symbols") or e.data.get("symbols") or []
            if isinstance(syms, list):
                symbols.update(str(s) for s in syms)
            elif isinstance(syms, str):
                symbols.add(syms)

            tests = e.data.get("failed_tests") or []
            if isinstance(tests, list):
                failed_tests.update(str(t) for t in tests)

            if e.outcome in ("needs_human", "failed", "blocked") and e.detail:
                blocker = e.detail

        return Checkpoint(
            candidate_id=candidate_id,
            last_outcome=last_entry.outcome,
            attempt_count=attempt_count or len(entries),
            total_spend_usd=total_spend,
            total_tokens=total_toks,
            target_symbols=sorted(symbols),
            failed_tests=sorted(failed_tests),
            blocker_reason=blocker,
            latest_ts=last_entry.ts,
        )


def render_resume_pack(checkpoint: Checkpoint) -> str:
    """Render a token-efficient (~100-150 token) ResumePack for a resuming worker."""
    lines: list[str] = []
    outcome = checkpoint.last_outcome
    lines.append(f"## 🔄 Prior Attempt Checkpoint (`{checkpoint.candidate_id}`)")
    lines.append(f"- **Attempt #{checkpoint.attempt_count + 1}** (Outcome: `{outcome}`)")
    lines.append(
        f"- **Cumulative Spend:** ${checkpoint.total_spend_usd:.4f} "
        f"({checkpoint.total_tokens} tokens)"
    )

    if checkpoint.target_symbols:
        syms_str = ", ".join(f"`{s}`" for s in checkpoint.target_symbols)
        lines.append(f"- **Target Symbols:** {syms_str}")

    if checkpoint.failed_tests:
        tests_str = ", ".join(f"`{t}`" for t in checkpoint.failed_tests)
        lines.append(f"- ⚠️ **Prior Test Failures:** {tests_str}")

    if checkpoint.blocker_reason:
        lines.append(f"- ⚠️ **Prior Blocker:** {checkpoint.blocker_reason}")

    lines.append("- **Directive:** Address prior failure/blocker without breaking interfaces.")
    lines.append("")

    return "\n".join(lines)
