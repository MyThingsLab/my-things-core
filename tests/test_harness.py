from pathlib import Path

from mythings._harness import harness_text, main, revendor, service_harness_text


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


def test_revendor_check_reports_without_writing(tmp_path: Path) -> None:
    (tmp_path / "my-stale").mkdir()
    (tmp_path / "my-stale" / "HARNESS.md").write_text("old rules", encoding="utf-8")

    stale, _ = revendor(tmp_path, check=True)
    assert stale == ["my-stale"]
    assert (tmp_path / "my-stale" / "HARNESS.md").read_text(encoding="utf-8") == "old rules"

    assert main([str(tmp_path), "--check"]) == 1
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--check"]) == 0
