from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType


def in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _git(repo: Path, argv: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


class Workspace:
    def __init__(self, repo: str | Path = ".", base_ref: str = "HEAD") -> None:
        self.repo = Path(repo).resolve()
        self.base_ref = base_ref
        self.path: Path | None = None
        self._tmp: str | None = None

    def __enter__(self) -> Path:
        self._tmp = tempfile.mkdtemp(prefix="mythings-ws-")
        tree = Path(self._tmp) / "tree"
        _git(self.repo, ["worktree", "add", "--detach", str(tree), self.base_ref])
        self.path = tree
        return tree

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # `worktree remove` failing leaves the repo genuinely inconsistent -- a
        # registered worktree pointing at a path nobody owns -- so it still
        # raises. Dropping the scratch dir is not in that category, and it must
        # happen even when the removal above did raise, or the leak compounds.
        try:
            if self.path is not None:
                _git(self.repo, ["worktree", "remove", "--force", str(self.path)])
                self.path = None
        finally:
            if self._tmp is not None:
                # Not `rmdir`: `worktree remove` empties `tree/`, but says nothing
                # about siblings of it, and this dir is only assumed to hold
                # `tree/`. Anything the body wrote here made cleanup raise *from
                # `__exit__`* -- after the body had already produced its result --
                # so a completed run was reported as a traceback and its outcome
                # discarded.
                #
                # Not hypothetical: a module that resolves a path by climbing out
                # of its own source tree lands here. `parents[3]` from
                # `<prefix>/tree/src/pkg/mod.py` is `<prefix>`, so a suite run in
                # the worktree creates the sibling on import.
                #
                # The prefix dir is ours by construction, so everything under it
                # is ours to delete, and failing to delete scratch is never worth
                # losing the body's outcome over.
                shutil.rmtree(self._tmp, ignore_errors=True)
                self._tmp = None
