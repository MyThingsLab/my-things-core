import json

import pytest

from mythings.engine import EngineRequest, EngineResult, NoopEngine
from mythings.selection import OrderedSelection, ordered_selection


class _ScriptedEngine:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.requests.append(request)
        return EngineResult(text=self.reply)


def _order_reply(order: list[str], reason: str = "because") -> str:
    return json.dumps({"order": order, "reason": reason})


def test_uses_the_engines_valid_order() -> None:
    items = [("a", "first item"), ("b", "second item"), ("c", "third item")]
    engine = _ScriptedEngine(_order_reply(["c", "a", "b"], "c is most urgent"))

    result = ordered_selection(items, engine, system="order these")

    expected = OrderedSelection(order=["c", "a", "b"], engine_used=True, reason="c is most urgent")
    assert result == expected


def test_prompt_carries_every_items_summary() -> None:
    items = [("a", "alpha summary"), ("b", "beta summary")]
    engine = _ScriptedEngine(_order_reply(["a", "b"]))
    ordered_selection(items, engine, system="order these")
    prompt = engine.requests[0].prompt
    assert "alpha summary" in prompt and "beta summary" in prompt


def test_falls_back_to_input_order_on_noop_engine() -> None:
    items = [("a", "x"), ("b", "y"), ("c", "z")]
    result = ordered_selection(items, NoopEngine(), system="order these")
    assert result.order == ["a", "b", "c"]
    assert result.engine_used is False


def test_falls_back_on_malformed_json() -> None:
    items = [("a", "x"), ("b", "y")]
    engine = _ScriptedEngine("not json")
    result = ordered_selection(items, engine, system="order these")
    assert result.order == ["a", "b"]
    assert result.engine_used is False


def test_falls_back_when_the_reply_drops_an_item() -> None:
    items = [("a", "x"), ("b", "y"), ("c", "z")]
    engine = _ScriptedEngine(_order_reply(["a", "b"]))  # missing "c"
    result = ordered_selection(items, engine, system="order these")
    assert result.order == ["a", "b", "c"]
    assert result.engine_used is False


def test_falls_back_when_the_reply_invents_an_unknown_id() -> None:
    items = [("a", "x"), ("b", "y")]
    engine = _ScriptedEngine(_order_reply(["a", "b", "ghost"]))
    result = ordered_selection(items, engine, system="order these")
    assert result.order == ["a", "b"]
    assert result.engine_used is False


def test_falls_back_when_the_reply_duplicates_an_id() -> None:
    items = [("a", "x"), ("b", "y")]
    engine = _ScriptedEngine(_order_reply(["a", "a"]))
    result = ordered_selection(items, engine, system="order these")
    assert result.order == ["a", "b"]
    assert result.engine_used is False


def test_uses_a_custom_fallback_order() -> None:
    items = [("a", "x"), ("b", "y"), ("c", "z")]
    result = ordered_selection(
        items, NoopEngine(), system="order these", fallback=["c", "b", "a"]
    )
    assert result.order == ["c", "b", "a"]


def test_rejects_duplicate_item_ids() -> None:
    items = [("a", "x"), ("a", "y")]
    with pytest.raises(ValueError, match="unique"):
        ordered_selection(items, NoopEngine(), system="order these")


def test_rejects_a_fallback_that_is_not_a_permutation() -> None:
    items = [("a", "x"), ("b", "y")]
    with pytest.raises(ValueError, match="permutation"):
        ordered_selection(items, NoopEngine(), system="order these", fallback=["a"])


def test_repairs_a_constraint_violation_in_the_engines_order() -> None:
    # "b" depends on "a" (a must come first); the Engine's reply violates it.
    items = [("a", "x"), ("b", "y")]
    engine = _ScriptedEngine(_order_reply(["b", "a"]))
    result = ordered_selection(
        items, engine, system="order these", constraints={"b": {"a"}}
    )
    assert result.order == ["a", "b"]
    assert result.engine_used is True  # the Engine's answer was accepted, then repaired


def test_repair_preserves_engine_preference_among_ready_items() -> None:
    # "c" depends on nothing; the Engine ranks it before "a"/"b". Only the
    # "b" <- "a" edge forces a swap -- "c" should stay wherever the Engine put
    # it relative to the others once dependencies are satisfied.
    items = [("a", "x"), ("b", "y"), ("c", "z")]
    engine = _ScriptedEngine(_order_reply(["c", "b", "a"]))
    result = ordered_selection(
        items, engine, system="order these", constraints={"b": {"a"}}
    )
    assert result.order == ["c", "a", "b"]


def test_repair_on_a_dependency_cycle_terminates() -> None:
    items = [("a", "x"), ("b", "y")]
    engine = _ScriptedEngine(_order_reply(["a", "b"]))
    result = ordered_selection(
        items, engine, system="order these", constraints={"a": {"b"}, "b": {"a"}}
    )
    assert sorted(result.order) == ["a", "b"]  # degrades to *a* valid-shaped output, not a hang


def test_repairs_the_fallback_order_too_when_constraints_are_given() -> None:
    items = [("a", "x"), ("b", "y")]
    result = ordered_selection(
        items,
        NoopEngine(),
        system="order these",
        fallback=["b", "a"],
        constraints={"b": {"a"}},
    )
    assert result.order == ["a", "b"]
