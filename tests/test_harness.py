from mythings._harness import harness_text


def test_harness_text_is_shipped_and_nonempty() -> None:
    text = harness_text()
    assert text.startswith("# MyThingsLab build harness")
    # A couple of load-bearing rules must survive any edit.
    assert "PR — never a merge" in text
    assert "separate from MoneyBallingAI" in text
