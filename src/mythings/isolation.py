from __future__ import annotations

import os
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
        if self.path is not None:
            _git(self.repo, ["worktree", "remove", "--force", str(self.path)])
            self.path = None
        if self._tmp is not None:
            # `worktree remove` empties `tree/`; drop the prefix dir we made.
            Path(self._tmp).rmdir()
            self._tmp = None
