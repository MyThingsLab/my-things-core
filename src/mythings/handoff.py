"""Standardized Inter-Tool Handoff Contract for Fleet Cycles.

Provides typed, token-efficient state transfer between fleet cycle stages:
Planner -> Researcher -> Scaffolder -> Coder -> Tester -> Reporter.

Eliminates token waste and duplicate discovery across tools by passing exact
symbols, blast radii, diff targets, and test assertions directly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

StageName = Literal[
    "planner",
    "researcher",
    "scaffolder",
    "coder",
    "tester",
    "reporter",
]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StageHandoff:
    """Structured handoff payload passed from one fleet tool stage to the next."""

    stage: StageName
    target_issue: str  # e.g. "my-coder#44"
    repo_name: str  # e.g. "my-coder"
    goal_id: str | None = None
    target_symbols: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    test_targets: list[str] = field(default_factory=list)
    context_pack_md: str | None = None
    assertions_passed: int = 0
    assertions_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageHandoff:
        return cls(
            stage=data["stage"],
            target_issue=data["target_issue"],
            repo_name=data["repo_name"],
            goal_id=data.get("goal_id"),
            target_symbols=data.get("target_symbols") or [],
            modified_files=data.get("modified_files") or [],
            test_targets=data.get("test_targets") or [],
            context_pack_md=data.get("context_pack_md"),
            assertions_passed=int(data.get("assertions_passed") or 0),
            assertions_failed=int(data.get("assertions_failed") or 0),
            metadata=data.get("metadata") or {},
            ts=data.get("ts") or _utc_now(),
        )

    @classmethod
    def from_json(cls, line: str) -> StageHandoff:
        return cls.from_dict(json.loads(line))

    def render_prompt_slice(self) -> str:
        """Render a token-efficient (~100-200 token) Markdown context slice for the next tool."""
        lines: list[str] = []
        lines.append(f"### 🤝 Inter-Tool Handoff (`{self.stage}` → next stage)")
        lines.append(f"- **Target Issue:** `{self.target_issue}` (`{self.repo_name}`)")

        if self.goal_id:
            lines.append(f"- **Goal Alignment:** `{self.goal_id}`")

        if self.target_symbols:
            syms_str = ", ".join(f"`{s}`" for s in self.target_symbols[:5])
            if len(self.target_symbols) > 5:
                syms_str += f" (+{len(self.target_symbols) - 5} more)"
            lines.append(f"- **Target Symbols:** {syms_str}")

        if self.modified_files:
            files_str = ", ".join(f"`{f}`" for f in self.modified_files[:5])
            lines.append(f"- **Modified Files:** {files_str}")

        if self.test_targets:
            tests_str = ", ".join(f"`{t}`" for t in self.test_targets[:5])
            lines.append(f"- **Test Verification Targets:** {tests_str}")

        if self.assertions_passed or self.assertions_failed:
            p, f = self.assertions_passed, self.assertions_failed
            lines.append(f"- **Assertions:** {p} passed, {f} failed")

        if self.context_pack_md:
            lines.append("\n#### 🎯 Scope Constraint Pack")
            lines.append(self.context_pack_md.strip())

        lines.append("")
        return "\n".join(lines)


def handoffs_dir(root: Path) -> Path:
    """Directory storing inter-tool handoff files for fleet cycles."""
    return root / ".my-fleet" / "handoffs"


def save_handoff(root: Path, handoff: StageHandoff) -> Path:
    """Save a StageHandoff payload to disk for downstream tool consumption."""
    h_dir = handoffs_dir(root)
    h_dir.mkdir(parents=True, exist_ok=True)
    sanitized_issue = handoff.target_issue.replace("/", "_").replace("#", "-")
    file_path = h_dir / f"{sanitized_issue}_{handoff.stage}.json"
    file_path.write_text(handoff.to_json(), encoding="utf-8")
    return file_path


def load_latest_handoff(
    root: Path, target_issue: str, stage: StageName | None = None
) -> StageHandoff | None:
    """Load the latest handoff for a given target issue and optional stage filter."""
    h_dir = handoffs_dir(root)
    if not h_dir.exists():
        return None

    sanitized_issue = target_issue.replace("/", "_").replace("#", "-")
    pattern = f"{sanitized_issue}_*.json" if stage is None else f"{sanitized_issue}_{stage}.json"

    files = sorted(h_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        return None

    try:
        return StageHandoff.from_json(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None
