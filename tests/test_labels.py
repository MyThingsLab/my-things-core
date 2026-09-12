from mythings.labels import (
    SCHEMA,
    Facets,
    QueueItem,
    parse,
    sort_key,
    sync,
    validate,
)
from mythings.testing import FakeGh


def test_schema_has_all_22_cad_labels() -> None:
    names = [label.name for label in SCHEMA]
    assert len(names) == 22
    assert len(set(names)) == 22  # no duplicates
    for prefix, count in (("lane:", 4), ("prio:", 4), ("kind:", 7), ("size:", 3), ("state:", 4)):
        assert sum(1 for n in names if n.startswith(prefix)) == count


def test_every_schema_label_has_a_color_and_description() -> None:
    for label in SCHEMA:
        assert label.color and label.description


def test_sync_creates_every_label_with_force_and_repo() -> None:
    fake = FakeGh({("label", "create"): ""})
    sync("o/r", runner=fake)

    assert len(fake.calls) == len(SCHEMA)
    for call, label in zip(fake.calls, SCHEMA, strict=True):
        assert call[:3] == ["label", "create", label.name]
        assert "--color" in call and label.color in call
        assert "--description" in call and label.description in call
        assert "--force" in call
        assert call[-2:] == ["--repo", "o/r"]


def test_sync_is_idempotent_against_a_repo_that_already_has_the_schema() -> None:
    # A second sync() against a repo that already has the schema must issue
    # the exact same idempotent --force calls, not skip or error.
    fake = FakeGh({("label", "create"): ""})
    sync("o/r", runner=fake)
    sync("o/r", runner=fake)

    assert len(fake.calls) == 2 * len(SCHEMA)
    assert fake.calls[0] == fake.calls[len(SCHEMA)]


def test_parse_extracts_known_facets() -> None:
    facets = parse(["lane:kernel", "prio:P1", "kind:bug", "size:M", "state:ready"])
    assert facets == Facets(lane="kernel", prio="P1", kind="bug", size="M", state="ready")


def test_parse_passes_unknown_labels_through_untouched() -> None:
    facets = parse(["my-idea", "lane:core", "help wanted"])
    assert facets.lane == "core"
    assert facets.unknown == ("my-idea", "help wanted")


def test_parse_treats_unrecognized_facet_value_as_unknown() -> None:
    facets = parse(["prio:P9"])
    assert facets.prio is None
    assert facets.unknown == ("prio:P9",)


def test_validate_requires_lane_and_size() -> None:
    result = validate(parse(["kind:bug"]))
    assert not result.dispatchable
    assert "missing lane" in result.reasons
    assert "missing size" in result.reasons


def test_validate_excludes_size_l() -> None:
    result = validate(parse(["lane:core", "size:L"]))
    assert not result.dispatchable
    assert any("size:L" in reason for reason in result.reasons)


def test_validate_excludes_state_blocked() -> None:
    result = validate(parse(["lane:core", "size:S", "state:blocked"]))
    assert not result.dispatchable
    assert any("blocked" in reason for reason in result.reasons)


def test_validate_passes_a_fully_specified_dispatchable_issue() -> None:
    result = validate(parse(["lane:core", "size:S", "state:ready", "prio:P1"]))
    assert result.dispatchable
    assert result.reasons == ()


def test_sort_key_ranks_critical_labels_first() -> None:
    normal = QueueItem(repo="o/r", number=1, labels=("lane:core",), age_days=1)
    critical = QueueItem(repo="o/r", number=2, labels=("critical",), age_days=0)
    assert sort_key(critical) < sort_key(normal)


def test_sort_key_orders_by_lane_then_prio_then_age_then_repo_then_number() -> None:
    items = [
        QueueItem(repo="z", number=1, labels=("lane:external", "prio:P0"), age_days=10),
        QueueItem(repo="a", number=2, labels=("lane:core", "prio:P3"), age_days=1),
        QueueItem(repo="a", number=1, labels=("lane:core", "prio:P3"), age_days=1),
        QueueItem(repo="b", number=1, labels=("lane:core", "prio:P0"), age_days=1),
        QueueItem(repo="c", number=1, labels=("lane:kernel", "prio:P0"), age_days=5),
        QueueItem(repo="c", number=2, labels=("lane:kernel", "prio:P0"), age_days=50),
        QueueItem(repo="d", number=1, labels=("critical",), age_days=0),
    ]

    ranked = sorted(items, key=sort_key)

    assert [(item.repo, item.number) for item in ranked] == [
        ("d", 1),  # critical wins outright
        ("b", 1),  # lane:core + prio:P0 beats lane:core + prio:P3
        ("a", 1),  # same lane/prio/age as (a, 2); (repo, number) tiebreak
        ("a", 2),
        ("c", 2),  # lane:kernel, prio:P0, oldest of the two kernel items
        ("c", 1),
        ("z", 1),  # lane:external loses to every core/kernel item despite prio:P0
    ]


def test_sort_key_has_no_ties_beyond_repo_and_number() -> None:
    items = [
        QueueItem(repo="a", number=1, labels=("lane:core", "prio:P1"), age_days=3),
        QueueItem(repo="b", number=2, labels=("lane:core", "prio:P1"), age_days=3),
    ]
    keys = [sort_key(item)[:-2] for item in items]
    assert keys[0] == keys[1]  # tie on everything but the (repo, number) tail
    assert sort_key(items[0]) != sort_key(items[1])  # broken by the tail itself
