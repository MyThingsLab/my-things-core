import json
from pathlib import Path

import pytest

from mythings._harness import harness_text, main, remote_stale, revendor, service_harness_text
from mythings.github import GitHubError


def test_harness_text_is_shipped_and_nonempty() -> None:
    text = harness_text()
    assert text.startswith("# MyThingsLab build harness")
    # A couple of load-bearing rules must survive any edit.
    assert "PR — never a merge" in text
    assert "isolated from other ventures" in text


def test_service_harness_text_is_shipped_and_nonempty() -> None:
    text = service_harness_text()
    assert text.startswith("# MyThingsLab service harness")
    # The invariants that genuinely differ from the tool harness must survive.
    assert "may not open a pr at all" in text.lower()
    assert "health/readiness surface" in text
    assert "is **not** issue-triggered" in text


def test_revendor_rewrites_stale_and_skips_fresh(tmp_path: Path) -> None:
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "HARNESS.md").write_text("old rules", encoding="utf-8")
    (tmp_path / "my-fresh").mkdir()
    (tmp_path / "my-fresh" / "HARNESS.md").write_text(harness_text(), encoding="utf-8")
    (tmp_path / "not-a-tool").mkdir()

    stale, fresh = revendor(tmp_path)
    assert stale == ["my-stale"]
    assert fresh == ["my-fresh"]
    assert (tmp_path / "my-stale" / "HARNESS.md").read_text(encoding="utf-8") == harness_text()
    assert not (tmp_path / "not-a-tool" / "HARNESS.md").exists()


def test_revendor_sweeps_service_harness_when_filename_given(tmp_path: Path) -> None:
    (tmp_path / "my-service").mkdir()
    (tmp_path / "my-service" / "SERVICE_HARNESS.md").write_text("old rules", encoding="utf-8")
    (tmp_path / "my-tool").mkdir()
    (tmp_path / "my-tool" / "HARNESS.md").write_text("old rules", encoding="utf-8")

    stale, fresh = revendor(tmp_path, filename="SERVICE_HARNESS.md")
    assert stale == ["my-service"]
    assert fresh == []
    assert (
        tmp_path / "my-service" / "SERVICE_HARNESS.md"
    ).read_text(encoding="utf-8") == service_harness_text()
    # A repo only vendoring the tool harness is untouched by a service sweep.
    assert (tmp_path / "my-tool" / "HARNESS.md").read_text(encoding="utf-8") == "old rules"


def test_revendor_check_reports_without_writing(tmp_path: Path) -> None:
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "HARNESS.md").write_text("old rules", encoding="utf-8")

    stale, _ = revendor(tmp_path, check=True)
    assert stale == ["my-stale"]
    assert (tmp_path / "my-stale" / "HARNESS.md").read_text(encoding="utf-8") == "old rules"

    assert main([str(tmp_path), "--check"]) == 1
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--check"]) == 0


def _fake_runner(
    repos: list[dict],
    contents: dict[str, str],
    pr_contents: dict[str, str] | None = None,
):
    # contents: repo -> HARNESS.md on the default branch.
    # pr_contents: repo -> HARNESS.md on that repo's one open PR head.
    pr_contents = pr_contents or {}

    def run(argv: list[str]) -> str:
        if argv[:2] == ["repo", "list"]:
            return json.dumps(repos)
        if argv[:2] == ["pr", "list"]:
            name = argv[argv.index("--repo") + 1].split("/")[1]
            return json.dumps([{"headRefOid": f"sha-{name}"}] if name in pr_contents else [])
        path, _, query = argv[1].partition("?")
        name = path.split("/")[2]  # repos/<org>/<name>/contents/HARNESS.md
        if query.startswith("ref="):
            if name not in pr_contents:
                raise GitHubError("gh api ... failed (1): Not Found")
            return pr_contents[name]
        if name not in contents:
            raise GitHubError(f"gh api repos/o/{name}/contents/HARNESS.md failed (1): Not Found")
        return contents[name]

    return run


def test_remote_stale_separates_stale_from_current() -> None:
    runner = _fake_runner(
        [{"name": "my-stale", "isArchived": False}, {"name": "my-fresh", "isArchived": False}],
        {"my-stale": "old rules", "my-fresh": harness_text()},
    )
    drift = remote_stale("o", runner=runner)
    assert (drift.stale, drift.in_flight, drift.current) == (["my-stale"], [], ["my-fresh"])


def test_remote_stale_ignores_archived_and_non_vendoring_repos() -> None:
    # An archived repo is read-only, so a stale copy there could never be
    # fixed -- counting it would pin the gate red forever. A repo with no
    # HARNESS.md simply isn't this gate's business.
    runner = _fake_runner(
        [
            {"name": "my-archived", "isArchived": True},
            {"name": "study", "isArchived": False},
            {"name": "my-fresh", "isArchived": False},
        ],
        {"my-archived": "old rules", "my-fresh": harness_text()},
    )
    drift = remote_stale("o", runner=runner)
    assert (drift.stale, drift.in_flight, drift.current) == ([], [], ["my-fresh"])


def test_an_open_sweep_pr_counts_as_handled_so_the_gate_cannot_deadlock() -> None:
    # The deadlock this guards against, which this gate's own first CI run hit:
    # a sibling's sweep PR is written against the new canonical, so it is red
    # until the core PR merges -- and the core PR is red until the sweep merges.
    # Neither can go green first. An open PR carrying the new copy is enough.
    runner = _fake_runner(
        [{"name": "my-swept", "isArchived": False}],
        {"my-swept": "old rules"},
        pr_contents={"my-swept": harness_text()},
    )
    drift = remote_stale("o", runner=runner)
    assert (drift.stale, drift.in_flight) == ([], ["my-swept"])


def test_an_open_pr_that_does_not_sweep_leaves_the_repo_stale() -> None:
    # Any open PR must not launder a stale repo -- only one that actually
    # carries the new copy counts.
    runner = _fake_runner(
        [{"name": "my-stale", "isArchived": False}],
        {"my-stale": "old rules"},
        pr_contents={"my-stale": "some unrelated change"},
    )
    drift = remote_stale("o", runner=runner)
    assert (drift.stale, drift.in_flight) == (["my-stale"], [])


def test_remote_stale_checks_service_harness_when_filename_given() -> None:
    runner = _fake_runner(
        [{"name": "my-service", "isArchived": False}],
        {"my-service": service_harness_text()},
    )
    drift = remote_stale("o", runner=runner, filename="SERVICE_HARNESS.md")
    assert (drift.stale, drift.in_flight, drift.current) == ([], [], ["my-service"])


def test_workspace_check_cannot_stand_in_for_the_remote_check(tmp_path: Path) -> None:
    # The reason --remote-check exists: core's CI checks out core alone, so a
    # workspace check there globs nothing and passes no matter how stale the
    # fleet is. Pin that, so nobody "simplifies" CI back to --check.
    assert main([str(tmp_path), "--check"]) == 0


def test_main_requires_a_workspace_or_an_org() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_sweeps_service_harness_when_filename_flag_given(tmp_path: Path) -> None:
    (tmp_path / "my-service").mkdir()
    (tmp_path / "my-service" / "SERVICE_HARNESS.md").write_text("old rules", encoding="utf-8")

    assert main([str(tmp_path), "--check", "--filename", "SERVICE_HARNESS.md"]) == 1
    assert main([str(tmp_path), "--filename", "SERVICE_HARNESS.md"]) == 0
    assert (
        tmp_path / "my-service" / "SERVICE_HARNESS.md"
    ).read_text(encoding="utf-8") == service_harness_text()
