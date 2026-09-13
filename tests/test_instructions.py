from pathlib import Path

from mythings.instructions import find_instruction_file, read_instructions


def test_find_instruction_file_priority(tmp_path: Path) -> None:
    # Empty
    assert find_instruction_file(tmp_path) is None
    assert read_instructions(tmp_path) == ""

    # CLAUDE.md only
    (tmp_path / "CLAUDE.md").write_text("claude content", encoding="utf-8")
    assert find_instruction_file(tmp_path) == tmp_path / "CLAUDE.md"
    assert read_instructions(tmp_path) == "claude content"

    # GEMINI.md overrides CLAUDE.md
    (tmp_path / "GEMINI.md").write_text("gemini content", encoding="utf-8")
    assert find_instruction_file(tmp_path) == tmp_path / "GEMINI.md"
    assert read_instructions(tmp_path) == "gemini content"

    # AGENTS.md takes top priority
    (tmp_path / "AGENTS.md").write_text("agents content", encoding="utf-8")
    assert find_instruction_file(tmp_path) == tmp_path / "AGENTS.md"
    assert read_instructions(tmp_path) == "agents content"
