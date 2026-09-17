import subprocess
from pathlib import Path

import pytest

from mythings._release import (
    SurfaceError,
    bump_kind,
    check,
    check_surface,
    check_version_changelog,
    latest_release_tag,
    main,
    module_exports,
    release_text,
    revendor,
    surface,
    surface_bump_errors,
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


# --- public surface vs. semver ------------------------------------------


def test_module_exports_reads_a_literal_list() -> None:
    assert module_exports("__all__ = ['b', 'a']\n", origin="m.py") == ["b", "a"]


def test_module_exports_reads_a_tuple_and_an_annotated_assignment() -> None:
    assert module_exports("__all__ = ('a',)\n", origin="m.py") == ["a"]
    assert module_exports("__all__: list[str] = ['a']\n", origin="m.py") == ["a"]


def test_module_exports_is_empty_when_all_is_absent() -> None:
    assert module_exports("x = 1\n", origin="m.py") == []


def test_module_exports_refuses_augmented_assignment() -> None:
    # Under-reporting the surface is the one failure this check cannot afford,
    # so a '+=' build-up must raise rather than return the first literal.
    with pytest.raises(SurfaceError, match="\\+="):
        module_exports("__all__ = ['a']\n__all__ += ['b']\n", origin="m.py")


def test_module_exports_refuses_a_computed_all() -> None:
    with pytest.raises(SurfaceError, match="computed"):
        module_exports("__all__ = [n for n in dir()]\n", origin="m.py")


def test_module_exports_refuses_a_conditional_all() -> None:
    source = "import sys\nif sys.version_info >= (3, 13):\n    __all__ = ['a']\n"
    with pytest.raises(SurfaceError, match="conditionally"):
        module_exports(source, origin="m.py")


def test_module_exports_takes_the_last_top_level_rebind() -> None:
    assert module_exports("__all__ = ['a']\n__all__ = ['b']\n", origin="m.py") == ["b"]


def test_module_exports_refuses_non_string_entries() -> None:
    with pytest.raises(SurfaceError, match="list of strings"):
        module_exports("__all__ = [1, 2]\n", origin="m.py")


def test_surface_qualifies_names_and_skips_private_modules() -> None:
    sources = {
        "src/pkg/__init__.py": "__all__ = ['Thing']\n",
        "src/pkg/public.py": "__all__ = ['helper']\n",
        "src/pkg/_tooling.py": "__all__ = ['not_surface']\n",
    }
    assert surface(sources) == {"pkg.Thing", "pkg.public.helper"}


def test_surface_counts_a_promotion_to_the_top_level_as_new() -> None:
    # Re-exporting an existing submodule symbol from the package root is new
    # reachable surface: `from pkg import helper` did not work before.
    before = surface({"src/pkg/public.py": "__all__ = ['helper']\n"})
    after = surface(
        {
            "src/pkg/__init__.py": "__all__ = ['helper']\n",
            "src/pkg/public.py": "__all__ = ['helper']\n",
        }
    )
    assert sorted(after - before) == ["pkg.helper"]


def test_bump_kind_classifies_each_component() -> None:
    assert bump_kind("1.7.0", "1.7.0") is None
    assert bump_kind("1.7.0", "1.7.1") == "patch"
    assert bump_kind("1.7.0", "1.8.0") == "minor"
    assert bump_kind("1.7.0", "2.0.0") == "major"


def test_bump_kind_refuses_a_backwards_or_malformed_version() -> None:
    with pytest.raises(SurfaceError, match="backwards"):
        bump_kind("1.8.0", "1.7.0")
    with pytest.raises(SurfaceError, match="MAJOR.MINOR.PATCH"):
        bump_kind("1.7.0", "1.8")


def _errors(baseline: set[str], head: set[str], head_version: str) -> list[str]:
    return surface_bump_errors(
        baseline=baseline,
        head=head,
        baseline_version="1.7.0",
        head_version=head_version,
        baseline_label="v1.7.0",
    )


def test_surface_growth_without_a_bump_is_rejected() -> None:
    # The #202 shape: a new export, version left where the last release put it.
    errors = _errors({"pkg.A"}, {"pkg.A", "pkg.B"}, "1.7.0")
    assert len(errors) == 1
    assert "grew" in errors[0]
    assert "pkg.B" in errors[0]


def test_surface_growth_with_a_patch_bump_is_rejected() -> None:
    errors = _errors({"pkg.A"}, {"pkg.A", "pkg.B"}, "1.7.1")
    assert len(errors) == 1
    assert "grew" in errors[0]


def test_surface_growth_with_a_minor_or_major_bump_is_accepted() -> None:
    assert _errors({"pkg.A"}, {"pkg.A", "pkg.B"}, "1.8.0") == []
    assert _errors({"pkg.A"}, {"pkg.A", "pkg.B"}, "2.0.0") == []


def test_surface_removal_needs_a_major_bump() -> None:
    errors = _errors({"pkg.A", "pkg.B"}, {"pkg.A"}, "1.8.0")
    assert len(errors) == 1
    assert "shrank" in errors[0]
    assert "pkg.B" in errors[0]
    assert _errors({"pkg.A", "pkg.B"}, {"pkg.A"}, "2.0.0") == []


def test_unchanged_surface_says_nothing_whatever_the_version_does() -> None:
    # An unbumped PR that touches no exports is legitimately silent -- this
    # check only rules on the surface, never on whether a bump was needed for
    # some other reason.
    assert _errors({"pkg.A"}, {"pkg.A"}, "1.7.0") == []
    assert _errors({"pkg.A"}, {"pkg.A"}, "1.7.1") == []


def _init_repo(repo: Path, version: str, exports: list[str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "src" / "pkg").mkdir(parents=True, exist_ok=True)
    _write_repo(repo, version, exports)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )


def _write_repo(repo: Path, version: str, exports: list[str]) -> None:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "pkg"\nversion = "{version}"\n', encoding="utf-8"
    )
    (repo / "src" / "pkg" / "__init__.py").write_text(
        "__all__ = [" + ", ".join(repr(e) for e in exports) + "]\n", encoding="utf-8"
    )


def test_check_surface_is_silent_before_the_first_release(tmp_path: Path) -> None:
    repo = tmp_path / "pkg"
    _init_repo(repo, "0.1.0", ["A"])
    assert latest_release_tag(repo) is None
    assert check_surface(repo) == []


@pytest.mark.slow
def test_check_surface_flags_growth_against_the_tag_not_the_branch(tmp_path: Path) -> None:
    # The reason the baseline is the tag: an unbumped addition that already
    # landed on main must keep failing for every later PR, not become the new
    # normal the way a base-branch diff would treat it.
    repo = tmp_path / "pkg"
    _init_repo(repo, "1.0.0", ["A"])
    subprocess.run(["git", "-C", str(repo), "tag", "v1.0.0"], check=True)

    _write_repo(repo, "1.0.0", ["A", "B"])
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "add B without a bump"],
        check=True,
    )
    errors = check_surface(repo)
    assert len(errors) == 1
    assert "pkg.B" in errors[0]

    # A later PR adding C still sees B as unaccounted-for surface.
    _write_repo(repo, "1.0.0", ["A", "B", "C"])
    errors = check_surface(repo)
    assert "pkg.B" in errors[0]
    assert "pkg.C" in errors[0]

    # Bumping MINOR clears both.
    _write_repo(repo, "1.1.0", ["A", "B", "C"])
    assert check_surface(repo) == []


@pytest.mark.slow
def test_main_check_surface_exits_nonzero_on_a_violation(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "pkg"
    _init_repo(repo, "1.0.0", ["A"])
    subprocess.run(["git", "-C", str(repo), "tag", "v1.0.0"], check=True)
    _write_repo(repo, "1.0.0", ["A", "B"])

    assert main(["--check-surface", str(repo)]) == 1
    assert "ERROR" in capsys.readouterr().out

    _write_repo(repo, "1.1.0", ["A", "B"])
    assert main(["--check-surface", str(repo)]) == 0


def test_legacy_workspace_cli_still_works(tmp_path: Path) -> None:
    # --check-surface is additive; RELEASE.md documents the positional form and
    # is vendored into five repos, so it must keep working unchanged.
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "RELEASE.md").write_text("old rules", encoding="utf-8")
    assert main([str(tmp_path), "--check"]) == 1


def test_cli_requires_a_workspace_unless_checking_surface() -> None:
    with pytest.raises(SystemExit):
        main([])
