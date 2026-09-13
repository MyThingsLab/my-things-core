from __future__ import annotations

from pathlib import Path

INSTRUCTION_FILENAMES = ("AGENTS.md", "GEMINI.md", "CLAUDE.md")


def find_instruction_file(repo_dir: Path) -> Path | None:
    for name in INSTRUCTION_FILENAMES:
        path = repo_dir / name
        if path.exists():
            return path
    return None


def read_instructions(repo_dir: Path) -> str:
    path = find_instruction_file(repo_dir)
    return path.read_text(encoding="utf-8") if path else ""
