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
            ts=obj["ts"],
        )


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
