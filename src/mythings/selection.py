from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mythings.engine import Engine, EngineRequest

# Three tools independently implement the same shape: assemble a candidate
# set, one Engine call to order/select within deterministic constraints,
# validate the reply is a permutation of the input, deterministic fallback
# under NoopEngine (my-planner's sequence, my-orchestrator's tie-break,
# my-conductor's merge order). This is the promoted helper -- a seam like
# plan.py/mastery.py, not a sixth load-bearing contract.


@dataclass(frozen=True)
class OrderedSelection:
    order: list[str]  # item ids, in chosen order -- always a permutation of the input ids
    engine_used: bool  # False when the Engine's reply was unusable and the fallback ran
    reason: str


def _is_permutation(candidate: object, known: set[str]) -> bool:
    return (
        isinstance(candidate, list)
        and all(isinstance(x, str) for x in candidate)
        and len(candidate) == len(known)
        and set(candidate) == known
    )


def _topological_repair(order: list[str], constraints: dict[str, set[str]]) -> list[str]:
    # Kahn's algorithm, tie-broken by `order`'s preference: among the ids
    # whose dependencies are already placed, the one the Engine (or fallback)
    # ranked earliest wins. This keeps the result as close as possible to that
    # judgment while guaranteeing every constraint is respected, rather than
    # emitting an arbitrary valid order.
    preference = {item_id: i for i, item_id in enumerate(order)}
    depends_on = {item_id: set(constraints.get(item_id, ())) for item_id in order}
    pending = set(order)
    repaired: list[str] = []
    while pending:
        ready = sorted(
            (item_id for item_id in pending if not (depends_on[item_id] & pending)),
            key=lambda item_id: preference[item_id],
        )
        if not ready:
            # A cycle in constraints -- emit whatever remains in preference
            # order rather than looping forever; a cycle is a caller bug, not
            # something to silently resolve one way or another.
            ready = sorted(pending, key=lambda item_id: preference[item_id])
        next_id = ready[0]
        repaired.append(next_id)
        pending.discard(next_id)
    return repaired


def ordered_selection(
    items: list[tuple[str, str]],
    engine: Engine,
    *,
    system: str,
    constraints: dict[str, set[str]] | None = None,
    fallback: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> OrderedSelection:
    # `items` is (id, summary) pairs: summary is what the model sees, id is
    # what the reply and the fallback are validated against -- this is the
    # only shape general enough to cover a PR ("#123: title"), a tool name, or
    # a plan-task title without my-conductor/my-planner/my-orchestrator each
    # inventing their own id/summary convention.
    ids = [item_id for item_id, _ in items]
    if len(set(ids)) != len(ids):
        raise ValueError("ordered_selection: item ids must be unique")
    known = set(ids)

    resolved_fallback = fallback if fallback is not None else list(ids)
    if not _is_permutation(resolved_fallback, known):
        raise ValueError("ordered_selection: fallback must be a permutation of the item ids")

    result = engine.run(
        EngineRequest(
            prompt="\n".join(f"{item_id}: {summary}" for item_id, summary in items),
            system=system,
            context=context or {},
        )
    )
    try:
        obj = json.loads(result.text) if result.text else {}
    except json.JSONDecodeError:
        obj = {}

    proposed = obj.get("order")
    if _is_permutation(proposed, known):
        order = proposed
        engine_used = True
        reason = str(obj.get("reason", ""))
    else:
        order = resolved_fallback
        engine_used = False
        reason = "Engine gave no usable ordering — deterministic fallback"

    if constraints:
        order = _topological_repair(order, constraints)

    return OrderedSelection(order=order, engine_used=engine_used, reason=reason)
