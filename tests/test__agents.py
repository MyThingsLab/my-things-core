from pathlib import Path

from mythings._agents import is_agents_symlink, migrate_repo, sweep_workspace


def test_migrate_repo_converts_claude_md_to_agents_and_creates_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "my-tool"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# instructions\n", encoding="utf-8")

    # Dry run check should report non-compliant
    ok, reason = migrate_repo(repo, check=True)
    assert not ok
    assert "needs rename" in reason

    # Real migration
    ok, _ = migrate_repo(repo, check=False)
    assert ok

    # Verify AGENTS.md exists and has original content
    agents = repo / "AGENTS.md"
    assert agents.is_file() and not agents.is_symlink()
    assert agents.read_text(encoding="utf-8") == "# instructions\n"

    # Verify CLAUDE.md and GEMINI.md are symlinks pointing to AGENTS.md
    claude = repo / "CLAUDE.md"
    gemini = repo / "GEMINI.md"
    assert is_agents_symlink(claude)
    assert is_agents_symlink(gemini)

    # Check now passes
    ok, _ = migrate_repo(repo, check=True)
    assert ok


def test_sweep_workspace_handles_root_and_children(tmp_path: Path) -> None:
    # Root repo
    (tmp_path / "CLAUDE.md").write_text("# root instructions\n", encoding="utf-8")
    
    # Child repo
    child = tmp_path / "my-test"
    child.mkdir()
    (child / "CLAUDE.md").write_text("# child instructions\n", encoding="utf-8")

    stale, fresh = sweep_workspace(tmp_path, check=False)
    assert len(stale) == 0

    assert (tmp_path / "AGENTS.md").exists()
    assert is_agents_symlink(tmp_path / "CLAUDE.md")
    assert is_agents_symlink(tmp_path / "GEMINI.md")

    assert (child / "AGENTS.md").exists()
    assert is_agents_symlink(child / "CLAUDE.md")
    assert is_agents_symlink(child / "GEMINI.md")

    # Running sweep with check=True should report zero stale
    stale_check, fresh_check = sweep_workspace(tmp_path, check=True)
    assert len(stale_check) == 0
