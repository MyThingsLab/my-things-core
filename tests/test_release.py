import subprocess
from pathlib import Path

import pytest

from mythings._release import (
    DynamicAllError,
    check,
    check_version_changelog,
    main,
    public_surface_at_ref,
    release_text,
    revendor,
    surface_delta_errors,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *argv],
        capture_output=True,
        text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com",
             "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _commit(repo: Path, version: str, all_lines: dict[str, str]) -> str:
    (repo / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    src = repo / "src" / "mythings"
    src.mkdir(parents=True, exist_ok=True)
    for name, all_src in all_lines.items():
        (src / name).write_text(all_src, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"v{version}")
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def test_public_surface_at_ref_unions_all_modules(git_repo: Path) -> None:
    sha = _commit(
        git_repo,
        "1.0.0",
        {
            "__init__.py": "__all__ = ['Foo']\n",
            "logging.py": "__all__ = ['configure']\n",
        },
    )
    assert public_surface_at_ref(git_repo, sha) == {"mythings.Foo", "mythings.logging.configure"}


def test_public_surface_ignores_module_with_no_all(git_repo: Path) -> None:
    sha = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n", "helper.py": "X = 1\n"})
    assert public_surface_at_ref(git_repo, sha) == {"mythings.Foo"}


def test_public_surface_raises_on_dynamic_all(git_repo: Path) -> None:
    sha = _commit(
        git_repo, "1.0.0", {"__init__.py": "_NAMES = ['Foo']\n__all__ = _NAMES + ['Bar']\n"}
    )
    with pytest.raises(DynamicAllError):
        public_surface_at_ref(git_repo, sha)


def test_surface_delta_silent_when_unchanged(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    head = _commit(git_repo, "1.0.1", {"__init__.py": "__all__ = ['Foo']\n"})
    assert surface_delta_errors(git_repo, base, head) == []


def test_surface_delta_fails_when_surface_grows_without_minor_bump(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    head = _commit(git_repo, "1.0.1", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    errors = surface_delta_errors(git_repo, base, head)
    assert len(errors) == 1
    assert "grew" in errors[0]
    assert "MINOR" in errors[0]


def test_surface_delta_passes_when_surface_grows_with_minor_bump(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    head = _commit(git_repo, "1.1.0", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    assert surface_delta_errors(git_repo, base, head) == []


def test_surface_delta_fails_when_surface_shrinks_without_major_bump(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    head = _commit(git_repo, "1.1.0", {"__init__.py": "__all__ = ['Foo']\n"})
    errors = surface_delta_errors(git_repo, base, head)
    assert len(errors) == 1
    assert "shrank" in errors[0]
    assert "MAJOR" in errors[0]


def test_surface_delta_passes_when_surface_shrinks_with_major_bump(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    head = _commit(git_repo, "2.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    assert surface_delta_errors(git_repo, base, head) == []


def test_surface_delta_reports_both_when_grown_and_shrunk_without_major(git_repo: Path) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    head = _commit(git_repo, "1.1.0", {"__init__.py": "__all__ = ['Foo', 'Baz']\n"})
    errors = surface_delta_errors(git_repo, base, head)
    assert len(errors) == 1
    assert "shrank" in errors[0]


def test_check_surface_cli_reports_mismatch(git_repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    head = _commit(git_repo, "1.0.1", {"__init__.py": "__all__ = ['Foo', 'Bar']\n"})
    exit_code = main(["check-surface", base, head, "--repo", str(git_repo)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "grew" in out
    assert "1 surface/version mismatch(es)" in out


def test_check_surface_cli_clean_exit(git_repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = _commit(git_repo, "1.0.0", {"__init__.py": "__all__ = ['Foo']\n"})
    head = _commit(git_repo, "1.0.1", {"__init__.py": "__all__ = ['Foo']\n"})
    exit_code = main(["check-surface", base, head, "--repo", str(git_repo)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "0 surface/version mismatch(es)" in out


def test_release_text_is_shipped_and_nonempty() -> None:
    text = release_text()
    assert text.startswith("# MyThingsLab release contract")
    # A couple of load-bearing rules must survive any edit.
    assert "one `git tag vX.Y.Z`" in text
    assert "deprecated-but-working in the prior" in text


def test_revendor_rewrites_stale_and_skips_fresh(tmp_path: Path) -> None:
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "RELEASE.md").write_text("old rules", encoding="utf-8")
    (tmp_path / "my-fresh").mkdir()
    (tmp_path / "my-fresh" / "RELEASE.md").write_text(release_text(), encoding="utf-8")
    (tmp_path / "not-a-tool").mkdir()

    stale, fresh = revendor(tmp_path)
    assert stale == ["my-stale"]
    assert fresh == ["my-fresh"]
    assert (tmp_path / "my-stale" / "RELEASE.md").read_text(encoding="utf-8") == release_text()
    assert not (tmp_path / "not-a-tool" / "RELEASE.md").exists()


def test_revendor_check_reports_without_writing(tmp_path: Path) -> None:
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "RELEASE.md").write_text("old rules", encoding="utf-8")

    stale, _ = revendor(tmp_path, check=True)
    assert stale == ["my-stale"]
    assert (tmp_path / "my-stale" / "RELEASE.md").read_text(encoding="utf-8") == "old rules"

    assert main([str(tmp_path), "--check"]) == 1


def test_check_version_changelog_ok(tmp_path: Path) -> None:
    repo = tmp_path / "my-example"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## [1.0.0] - 2026-07-20\n- initial\n", encoding="utf-8")

    assert check_version_changelog(repo) == []


def test_check_version_changelog_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "my-example"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## [1.0.0] - 2026-07-20\n- initial\n", encoding="utf-8")

    errors = check_version_changelog(repo)
    assert len(errors) == 1
    assert "1.1.0" in errors[0]


def test_check_version_changelog_duplicate_heading(tmp_path: Path) -> None:
    repo = tmp_path / "my-example"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nversion = "1.2.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(
        "## [1.2.0] - 2026-07-21\n- second\n\n## [1.2.0] - 2026-07-20\n- first\n",
        encoding="utf-8",
    )

    errors = check_version_changelog(repo)
    assert len(errors) == 1
    assert "more than one" in errors[0]
    assert "[1.2.0]" in errors[0]


def test_check_version_changelog_missing_pyproject(tmp_path: Path) -> None:
    repo = tmp_path / "my-example"
    repo.mkdir()

    errors = check_version_changelog(repo)
    assert len(errors) == 1
    assert "no pyproject.toml version" in errors[0]


def test_check_sweeps_only_workspace_v1_repos(tmp_path: Path) -> None:
    v1 = tmp_path / "my-v1"
    v1.mkdir()
    (v1 / "RELEASE.md").write_text(release_text(), encoding="utf-8")
    (v1 / "pyproject.toml").write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")
    (v1 / "CHANGELOG.md").write_text("## [1.0.0] - 2026-07-20\n", encoding="utf-8")

    v0 = tmp_path / "my-v0"
    v0.mkdir()
    (v0 / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n', encoding="utf-8")

    errors = check(tmp_path)
    assert len(errors) == 1
    assert "my-v1" in errors[0]


def test_core_own_version_changelog_agree() -> None:
    # my-things-core is itself a v1 repo (authors release.md rather than
    # vendoring a copy), so it must satisfy the same contract it defines.
    assert check_version_changelog(REPO_ROOT) == []
