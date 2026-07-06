import subprocess
from pathlib import Path

from mythings.isolation import Workspace, in_github_actions


def _init_repo(path: Path) -> None:
    def git(*argv: str) -> None:
        subprocess.run(["git", "-C", str(path), *argv], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    (path / "marker.txt").write_text("base\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")


def test_workspace_yields_isolated_tree_and_cleans_up(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    with Workspace(repo) as tree:
        assert (tree / "marker.txt").read_text() == "base\n"
        # Edits in the worktree do not touch the source checkout.
        (tree / "marker.txt").write_text("changed\n")
        recorded = tree

    assert not recorded.exists()
    assert (repo / "marker.txt").read_text() == "base\n"
    worktrees = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list"],
        capture_output=True,
        text=True,
    ).stdout
    assert "mythings-ws-" not in worktrees


def test_in_github_actions(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert not in_github_actions()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert in_github_actions()
