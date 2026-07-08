import mythings._devledger as devledger


def test_main_add_then_show_filters_by_kind(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rc_add1 = devledger.main(
        ["add", "decision", "--detail", "chose approach A", "--session", "s1"]
    )
    assert rc_add1 == 0

    rc_add2 = devledger.main(
        ["add", "build", "--detail", "wired up CI", "--session", "s1"]
    )
    assert rc_add2 == 0

    ledger_file = tmp_path / "dev-ledger" / "s1.jsonl"
    assert ledger_file.exists()

    rc_show_all = devledger.main(["show", "--session", "s1"])
    assert rc_show_all == 0
    out_all = capsys.readouterr().out
    assert "chose approach A" in out_all
    assert "wired up CI" in out_all

    rc_show_filtered = devledger.main(["show", "--session", "s1", "--kind", "decision"])
    assert rc_show_filtered == 0
    out_filtered = capsys.readouterr().out
    assert "chose approach A" in out_filtered
    assert "wired up CI" not in out_filtered
    assert "success" in out_filtered
