import subprocess
from pathlib import Path

import pytest

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


def test_a_sibling_of_the_tree_does_not_break_cleanup(tmp_path: Path) -> None:
    # The prefix dir was removed with `rmdir`, which needs `tree/` to be its only
    # entry. A module that resolves a path by climbing out of its own source tree
    # lands right here -- `parents[3]` from `<prefix>/tree/src/pkg/mod.py` is
    # `<prefix>` -- so running a suite in the worktree creates the sibling and
    # cleanup raised OSError(ENOTEMPTY).
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    with Workspace(repo) as tree:
        (tree.parent / ".some-tool").mkdir()
        (tree.parent / ".some-tool" / "ledger.jsonl").write_text("{}\n")
        prefix = tree.parent

    assert not prefix.exists()


def test_cleanup_does_not_replace_the_body_s_own_failure(tmp_path: Path) -> None:
    # The raise came from `__exit__`, after the body had produced its result, so
    # a run that reached a real outcome was reported as OSError instead. Whatever
    # the body raises is what the caller must see.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    prefix: Path | None = None
    with pytest.raises(ValueError, match="the body's own problem"):
        with Workspace(repo) as tree:
            (tree.parent / "sibling").mkdir()
            prefix = tree.parent
            raise ValueError("the body's own problem")

    assert prefix is not None and not prefix.exists()


def test_a_failed_worktree_removal_still_raises_but_drops_the_scratch_dir(
    tmp_path: Path,
) -> None:
    # An unremovable worktree leaves the repo genuinely inconsistent, so that one
    # keeps raising -- unlike a scratch dir nothing depends on. The scratch dir
    # must still go, or a failure on that path leaks on top of itself.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ws = Workspace(repo)
    tree = ws.__enter__()
    prefix = tree.parent
    # Remove it out from under the Workspace so its own removal fails.
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(RuntimeError, match="worktree remove"):
        ws.__exit__(None, None, None)

    assert not prefix.exists()


def test_in_github_actions(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert not in_github_actions()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert in_github_actions()
