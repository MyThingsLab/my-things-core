from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from mythings.github import Runner, _gh


@dataclass(frozen=True)
class LabelDef:
    name: str
    color: str
    description: str


# The 23-label CAD schema, one canonical table. `sync()` and `parse()` both
# read from this instead of each hand-rolling the vocabulary, so the schema
# can only drift by editing this one list.
SCHEMA: tuple[LabelDef, ...] = (
    LabelDef("lane:core", "5319e7", "SDK / contract work in my-things-core itself"),
    LabelDef("lane:kernel", "1d76db", "One of the 9 kernel repos the fleet is built from"),
    LabelDef("lane:product", "0e8a16", "A My[X] product tool built on the kernel"),
    LabelDef(
        "lane:external",
        "c5def5",
        "Work outside the fleet's own repos (a dependency, a third-party integration)",
    ),
    LabelDef("prio:P0", "b60205", "Blocking — nothing else should dispatch ahead of this"),
    LabelDef("prio:P1", "d93f0b", "Urgent — dispatch before P2/P3 backlog"),
    LabelDef("prio:P2", "fbca04", "Normal priority"),
    LabelDef("prio:P3", "c2e0c6", "Low priority — nice to have"),
    LabelDef("kind:bug", "ee0701", "Incorrect behavior, not a missing feature"),
    LabelDef("kind:feat", "0e8a16", "New capability"),
    LabelDef("kind:test", "1d76db", "Test-only change (coverage, fixtures, regression)"),
    LabelDef("kind:docs", "0075ca", "Documentation only"),
    LabelDef("kind:chore", "cfd3d7", "Maintenance — deps, CI, cleanup, no behavior change"),
    LabelDef("kind:design", "d4c5f9", "Design/planning artifact, not yet code"),
    LabelDef("kind:seam", "5319e7", "A contract or interface boundary between tools"),
    LabelDef("size:S", "c2e0c6", "Small — a focused, single-file change"),
    LabelDef("size:M", "fbca04", "Medium — spans a few files or one seam"),
    LabelDef("size:L", "e99695", "Large — needs decomposition before dispatch"),
    LabelDef("state:ready", "0e8a16", "Dispatchable now"),
    LabelDef("state:blocked", "b60205", "Waiting on a dependency; not dispatchable"),
    LabelDef("state:needs-human", "fbca04", "Needs a human decision before a worker can proceed"),
    LabelDef("state:in-flight", "1d76db", "Already claimed by a worker"),
    # Deliberately unprefixed, and deliberately the only label that is not part
    # of a facet: it is an override on the whole ordering rather than a value
    # within one, and giving it a facet would invite a second value nobody
    # could rank against the first. `sort_key` has always read it; until it was
    # listed here `sync()` never created it, so the one thing that outranks
    # everything was missing on whichever repos nobody had labelled by hand.
    LabelDef(
        "critical",
        "b60205",
        "Outranks every lane and priority — an incident, not a backlog item",
    ),
)

# lane/prio dispatch order, lowest rank first -- also doubles as the allowed
# value set for parse()/validate() (kind/size/state have no ranking, so their
# allowed sets are derived from SCHEMA directly).
_LANE_ORDER: tuple[str, ...] = ("core", "kernel", "product", "external")
_PRIO_ORDER: tuple[str, ...] = ("P0", "P1", "P2", "P3")

_FACET_VALUES: dict[str, frozenset[str]] = {
    "lane": frozenset(_LANE_ORDER),
    "prio": frozenset(_PRIO_ORDER),
    "kind": frozenset(
        label.name.partition(":")[2] for label in SCHEMA if label.name.startswith("kind:")
    ),
    "size": frozenset(
        label.name.partition(":")[2] for label in SCHEMA if label.name.startswith("size:")
    ),
    "state": frozenset(
        label.name.partition(":")[2] for label in SCHEMA if label.name.startswith("state:")
    ),
}


@dataclass(frozen=True)
class Facets:
    lane: str | None = None
    prio: str | None = None
    kind: str | None = None
    size: str | None = None
    state: str | None = None
    # Every label that wasn't a recognized "<facet>:<value>" pair -- backlog
    # labels like `my-idea`, a tool's own backlog label, a stray typo. Passed
    # through untouched rather than dropped, so a caller can still see them.
    unknown: tuple[str, ...] = ()


def parse(labels: Sequence[str]) -> Facets:
    facets: dict[str, str] = {}
    unknown: list[str] = []
    for raw in labels:
        prefix, sep, value = raw.partition(":")
        if sep and prefix in _FACET_VALUES and value in _FACET_VALUES[prefix]:
            facets[prefix] = value
        else:
            unknown.append(raw)
    return Facets(
        lane=facets.get("lane"),
        prio=facets.get("prio"),
        kind=facets.get("kind"),
        size=facets.get("size"),
        state=facets.get("state"),
        unknown=tuple(unknown),
    )


@dataclass(frozen=True)
class Validation:
    dispatchable: bool
    reasons: tuple[str, ...] = ()


def validate(facets: Facets) -> Validation:
    reasons: list[str] = []
    if facets.lane is None:
        reasons.append("missing lane")
    if facets.size is None:
        reasons.append("missing size")
    elif facets.size == "L":
        reasons.append("size:L is too large to dispatch as-is; split it first")
    if facets.state == "blocked":
        reasons.append("state:blocked is not dispatchable")
    return Validation(dispatchable=not reasons, reasons=tuple(reasons))


@dataclass(frozen=True)
class QueueItem:
    repo: str
    number: int
    labels: tuple[str, ...] = field(default_factory=tuple)
    age_days: float = 0.0


def _rank(value: str | None, order: tuple[str, ...]) -> int:
    # An unranked (missing or unrecognized) value sorts after every known
    # one -- fail closed, same as plan.ready() treating a dangling dependency
    # as unmet rather than assuming the best case.
    return order.index(value) if value in order else len(order)


def sort_key(
    issue: QueueItem,
) -> tuple[bool, int, int, float, str, int]:
    # Lexicographic, no tuning constants -- explainable in one line: not
    # critical, then priority, then lane, then oldest first, then a
    # deterministic tiebreak on (repo, number).
    #
    # Priority outranks lane, and the order of those two is the whole design.
    # Lane-first was tried and is wrong: it makes `prio:P0` mean "first within
    # its lane", so a `lane:core` docs typo dispatches ahead of a `lane:kernel`
    # P0 security bug -- (True, 0, 3) < (True, 1, 0). That is not what the
    # label says ("Blocking -- nothing else should dispatch ahead of this"),
    # and a priority nobody can trust to mean what it says stops being used.
    # Lane still decides among equals, so a core P0 leads the P0s and "core
    # stays stable" survives as a tiebreak rather than as a veto.
    facets = parse(issue.labels)
    critical = "critical" in issue.labels
    lane_rank = _rank(facets.lane, _LANE_ORDER)
    prio_rank = _rank(facets.prio, _PRIO_ORDER)
    return (not critical, prio_rank, lane_rank, -issue.age_days, issue.repo, issue.number)


def sync(repo: str, *, runner: Runner = _gh) -> None:
    # `gh label create --force` creates the label if it's absent and
    # overwrites color/description if it already exists -- idempotent against
    # a repo that already has the schema without a separate list-then-diff
    # step.
    for label in SCHEMA:
        runner(
            [
                "label",
                "create",
                label.name,
                "--color",
                label.color,
                "--description",
                label.description,
                "--force",
                "--repo",
                repo,
            ]
        )
