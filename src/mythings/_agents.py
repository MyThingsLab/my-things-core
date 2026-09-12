from __future__ import annotations

import argparse
import os
from pathlib import Path

# Build tooling, not a contract — not exported from the public API.
# Ensures every tool in the workspace has a canonical AGENTS.md, with CLAUDE.md
# and GEMINI.md symlinked to it so Claude Code, Gemini CLI, and Antigravity
# read the identical instructions with zero drift.


def is_agents_symlink(link_path: Path, target_name: str = "AGENTS.md") -> bool:
    if not link_path.is_symlink():
        return False
    try:
        return os.readlink(link_path) == target_name
    except OSError:
        return False


def migrate_repo(repo_dir: Path, *, check: bool = False) -> tuple[bool, str]:
    """Ensure repo_dir has canonical AGENTS.md with CLAUDE.md and GEMINI.md symlinks."""
    agents_md = repo_dir / "AGENTS.md"
    claude_md = repo_dir / "CLAUDE.md"
    gemini_md = repo_dir / "GEMINI.md"

    # Step 1: Ensure AGENTS.md exists
    if not agents_md.exists() or agents_md.is_symlink():
        if claude_md.exists() and not claude_md.is_symlink():
            if check:
                return False, f"{repo_dir.name}: CLAUDE.md needs rename to AGENTS.md"
            claude_md.rename(agents_md)
        elif gemini_md.exists() and not gemini_md.is_symlink():
            if check:
                return False, f"{repo_dir.name}: GEMINI.md needs rename to AGENTS.md"
            gemini_md.rename(agents_md)
        else:
            return True, f"{repo_dir.name}: no instruction files found (skipped)"

    # Step 2: Ensure CLAUDE.md is a symlink to AGENTS.md
    if not is_agents_symlink(claude_md):
        if check:
            return False, f"{repo_dir.name}: CLAUDE.md is not a symlink to AGENTS.md"
        claude_md.unlink(missing_ok=True)
        claude_md.symlink_to("AGENTS.md")

    # Step 3: Ensure GEMINI.md is a symlink to AGENTS.md
    if not is_agents_symlink(gemini_md):
        if check:
            return False, f"{repo_dir.name}: GEMINI.md is not a symlink to AGENTS.md"
        gemini_md.unlink(missing_ok=True)
        gemini_md.symlink_to("AGENTS.md")

    return True, f"{repo_dir.name}: OK"


def sweep_workspace(workspace: Path, *, check: bool = False) -> tuple[list[str], list[str]]:
    """Migrate or check workspace root and all sibling repos."""
    stale: list[str] = []
    fresh: list[str] = []

    # Check workspace root itself
    ok, _ = migrate_repo(workspace, check=check)
    if ok:
        fresh.append(workspace.name or "root")
    else:
        stale.append(workspace.name or "root")

    # Check sibling repos
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "__")):
            continue
        has_repo_marker = (
            (child / ".git").exists()
            or (child / "pyproject.toml").exists()
            or (child / "CLAUDE.md").exists()
            or (child / "AGENTS.md").exists()
        )
        if not has_repo_marker:
            continue

        ok, _ = migrate_repo(child, check=check)
        if ok:
            fresh.append(child.name)
        else:
            stale.append(child.name)

    return stale, fresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mythings._agents",
        description="Migrate and enforce canonical AGENTS.md with CLAUDE.md/GEMINI.md symlinks.",
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help="MyThingsLab workspace root (parent of the tool checkouts)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report non-compliant repos without modifying; exit 1 if any found",
    )
    args = parser.parse_args(argv)

    stale, fresh = sweep_workspace(args.workspace, check=args.check)
    verb = "non-compliant" if args.check else "migrated"
    for name in stale:
        print(f"{verb}: {name}")
    print(f"{len(stale)} {verb}, {len(fresh)} already compliant")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
