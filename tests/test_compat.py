from pathlib import Path

import pytest

from mythings._compat import (
    check_claims,
    check_environment,
    check_imports,
    main,
    resolves,
)
from mythings._manifest import ToolEntry


def _tool(repo: str, status: str, depends_on: list[str]) -> ToolEntry:
    return ToolEntry(
        tool=repo,
        repo=repo,
        package=repo.replace("-", ""),
        title="",
        added="2026-07-09",
        status=status,
        backlog_label=repo,
        engine_call="none",
        ledger_kinds=[],
        depends_on=depends_on,
    )


def test_resolves_finds_public_exports_and_github_methods() -> None:
    assert resolves("Ledger")  # a public export
    assert resolves("open_pr")  # a GitHub client method
    assert not resolves("teleport")


def test_the_real_fleet_has_no_broken_core_claims() -> None:
    # The gate, against the shipped manifest. Every unmet core: claim today
    # belongs to an unbuilt tool, so this passes while still catching the day
    # core drops a capability a shipped tool declared.
    report = check_claims()
    assert report.ok, "\n".join(report.errors)


def test_a_shipped_tool_with_an_unmet_core_claim_is_an_error() -> None:
    report = check_claims([_tool("my-thing", "shipped", ["core:teleport"])])
    assert not report.ok
    assert "my-thing needs core:teleport" in report.errors[0]


def test_an_unbuilt_tools_unmet_claim_is_pending_not_fatal() -> None:
    report = check_claims([_tool("my-thing", "designed", ["core:teleport"])])
    assert report.ok
    assert "tool is designed" in report.pending[0]


def test_a_shipped_tool_may_not_depend_on_an_unbuilt_tool() -> None:
    tools = [
        _tool("my-thing", "shipped", ["tool:my-other"]),
        _tool("my-other", "designed", []),
    ]
    report = check_claims(tools)
    assert not report.ok
    assert "which is only designed" in report.errors[0]


def test_an_unknown_tool_dependency_is_an_error() -> None:
    report = check_claims([_tool("my-thing", "designed", ["tool:my-ghost"])])
    assert not report.ok
    assert "not in the fleet" in report.errors[0]


def test_an_unreadable_dependency_is_an_error() -> None:
    report = check_claims([_tool("my-thing", "designed", ["nonsense"])])
    assert not report.ok
    assert "unreadable dependency" in report.errors[0]


def _write_tool(workspace: Path, repo: str, body: str) -> None:
    package = workspace / repo / "src" / repo.replace("-", "")
    package.mkdir(parents=True)
    (package / "tool.py").write_text(body, encoding="utf-8")


def test_import_scan_accepts_symbols_core_still_provides(tmp_path: Path) -> None:
    _write_tool(tmp_path, "my-thing", "from mythings.ledger import Ledger\n")
    report = check_imports(tmp_path, [_tool("my-thing", "shipped", [])])
    assert report.ok
    assert "1 symbol imports resolved" in report.notes[-1]


def test_import_scan_catches_a_symbol_core_dropped(tmp_path: Path) -> None:
    _write_tool(tmp_path, "my-thing", "from mythings.ledger import Teleporter\n")
    report = check_imports(tmp_path, [_tool("my-thing", "shipped", [])])
    assert not report.ok
    assert "core no longer provides" in report.errors[0]


def test_import_scan_catches_a_module_core_dropped(tmp_path: Path) -> None:
    _write_tool(tmp_path, "my-thing", "from mythings.warp import Drive\n")
    report = check_imports(tmp_path, [_tool("my-thing", "shipped", [])])
    assert not report.ok
    assert "imports missing mythings.warp" in report.errors[0]


def test_import_scan_ignores_unbuilt_tools_and_absent_checkouts(tmp_path: Path) -> None:
    report = check_imports(tmp_path, [_tool("my-thing", "shipped", [])])
    assert report.ok
    assert "no local checkout, skipped" in report.notes[0]


def test_import_scan_survives_an_unparseable_file(tmp_path: Path) -> None:
    _write_tool(tmp_path, "my-thing", "this is not python (((\n")
    report = check_imports(tmp_path, [_tool("my-thing", "shipped", [])])
    assert report.ok


def test_environment_is_clean_outside_a_core_checkout(tmp_path: Path) -> None:
    report = check_environment(cwd=tmp_path)
    assert report.ok
    assert "resolves to" in report.notes[0]


def test_environment_flags_a_core_checkout_the_venv_does_not_serve(tmp_path: Path) -> None:
    # The worktree trap: editing src/mythings here while `import mythings`
    # resolves to a different tree entirely.
    decoy = tmp_path / "src" / "mythings"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("", encoding="utf-8")

    report = check_environment(cwd=tmp_path)
    assert not report.ok
    assert "the installed core is a different tree" in report.errors[0]
    assert "PYTHONPATH=" in report.errors[0]


def test_environment_accepts_the_checkout_the_venv_actually_serves() -> None:
    import mythings

    checkout = Path(mythings.__file__).resolve().parents[2]
    assert check_environment(cwd=checkout).ok


def test_cli_reports_and_exits_zero_on_a_healthy_fleet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "0 error(s)" in out
    # Whether any claims are PENDING depends on how many tools are still
    # unbuilt at any given moment; the CLI's pending rendering is covered
    # deterministically by test_an_unbuilt_tools_unmet_claim_is_pending_not_fatal.


def test_cli_exits_nonzero_when_check_finds_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "mythings._compat.check_claims",
        lambda *a, **k: check_claims([_tool("my-thing", "shipped", ["core:teleport"])]),
    )
    assert main(["--check"]) == 1
    assert "ERROR" in capsys.readouterr().out
