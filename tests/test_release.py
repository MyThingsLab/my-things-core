from pathlib import Path

from mythings._release import (
    check,
    check_version_changelog,
    main,
    release_text,
    revendor,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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
