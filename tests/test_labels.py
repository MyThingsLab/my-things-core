from mythings.labels import (
    SCHEMA,
    Facets,
    QueueItem,
    escalate,
    parse,
    sort_key,
    sync,
    validate,
)
from mythings.testing import FakeGh


def test_schema_has_all_23_cad_labels() -> None:
    names = [label.name for label in SCHEMA]
    assert len(names) == 23
    assert len(set(names)) == 23  # no duplicates
    for prefix, count in (("lane:", 4), ("prio:", 4), ("kind:", 7), ("size:", 3), ("state:", 4)):
        assert sum(1 for n in names if n.startswith(prefix)) == count
    assert "critical" in names


def test_the_label_that_outranks_everything_is_one_sync_can_create() -> None:
    # It was not. `sort_key` read `critical` from day one, but it was never a
    # SCHEMA entry, so sync() never created it -- it existed only where someone
    # had added it by hand, and was missing on the repo holding three of the
    # five open P0s. An override nobody can apply is not an override.
    assert any(label.name == "critical" for label in SCHEMA)


def test_critical_is_unprefixed_so_it_does_not_become_a_facet_value() -> None:
    # It overrides the whole ordering rather than being a value within one
    # facet; parse() must keep passing it through as unknown.
    assert parse(("critical", "lane:core")).unknown == ("critical",)
    assert parse(("critical", "lane:core")).lane == "core"


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


def test_validate_requires_lane_prio_and_size() -> None:
    result = validate(parse(["kind:bug"]))
    assert not result.dispatchable
    assert "missing lane" in result.reasons
    assert "missing prio" in result.reasons
    assert "missing size" in result.reasons


def test_validate_excludes_size_l() -> None:
    result = validate(parse(["lane:core", "prio:P1", "size:L"]))
    assert not result.dispatchable
    assert any("size:L" in reason for reason in result.reasons)


def test_validate_excludes_state_blocked() -> None:
    result = validate(parse(["lane:core", "prio:P1", "size:S", "state:blocked"]))
    assert not result.dispatchable
    assert any("blocked" in reason for reason in result.reasons)


def test_validate_passes_a_fully_specified_dispatchable_issue() -> None:
    result = validate(parse(["lane:core", "size:S", "state:ready", "prio:P1"]))
    assert result.dispatchable
    assert result.reasons == ()


def test_escalate_promotes_an_unprioritized_core_bug_to_p0() -> None:
    result = escalate(["lane:core", "kind:bug", "size:S"])
    assert result.labels == ("lane:core", "kind:bug", "size:S", "prio:P0")
    assert result.reason is not None


def test_escalate_overrides_a_priority_the_filer_already_chose() -> None:
    # The whole point: a filer that guessed P2 for a kernel bug does not get to
    # bury it. Lowering it back down is a human's call, made on the issue.
    result = escalate(["lane:kernel", "prio:P2", "kind:bug"])
    assert result.labels == ("lane:kernel", "prio:P0", "kind:bug")
    assert "prio:P2" in (result.reason or "")


def test_escalate_leaves_product_and_external_bugs_alone() -> None:
    for lane in ("lane:product", "lane:external"):
        result = escalate([lane, "prio:P3", "kind:bug"])
        assert result.labels == (lane, "prio:P3", "kind:bug")
        assert result.reason is None


def test_escalate_only_promotes_bugs_not_every_core_issue() -> None:
    # A core docs typo outranking the fleet is the failure this is correcting,
    # not one it should reintroduce from the other end.
    result = escalate(["lane:core", "prio:P3", "kind:docs"])
    assert result.labels == ("lane:core", "prio:P3", "kind:docs")
    assert result.reason is None


def test_escalate_is_idempotent_on_an_already_p0_bug() -> None:
    labels = ["lane:core", "prio:P0", "kind:bug"]
    result = escalate(labels)
    assert result.labels == tuple(labels)
    assert result.reason is None  # nothing to explain, so nothing is said


def test_escalate_needs_a_lane_to_act_on() -> None:
    # An unlabelled bug is triage's problem, not this function's -- guessing a
    # lane here would let a product bug promote itself by omission.
    assert escalate(["kind:bug"]).reason is None


def test_escalate_promotes_a_core_bug_above_everything_but_critical() -> None:
    # The end-to-end claim: escalate() feeds sort_key(), and the promoted issue
    # actually reaches the front of the queue.
    filed = escalate(["lane:kernel", "kind:bug", "size:S"])
    promoted = QueueItem(repo="o/r", number=2, labels=filed.labels, age_days=0)
    old_core_backlog = QueueItem(
        repo="o/r", number=1, labels=("lane:core", "prio:P1", "size:S"), age_days=400
    )
    assert sort_key(promoted) < sort_key(old_core_backlog)


def test_sort_key_ranks_critical_labels_first() -> None:
    normal = QueueItem(repo="o/r", number=1, labels=("lane:core",), age_days=1)
    critical = QueueItem(repo="o/r", number=2, labels=("critical",), age_days=0)
    assert sort_key(critical) < sort_key(normal)


def test_sort_key_orders_by_prio_then_lane_then_age_then_repo_then_number() -> None:
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
        ("b", 1),  # every P0 first; lane:core leads them
        ("c", 2),  # lane:kernel P0, oldest of the two kernel items
        ("c", 1),
        ("z", 1),  # lane:external, but still a P0, so still ahead of any P3
        ("a", 1),  # P3 last, (repo, number) breaking the tie with (a, 2)
        ("a", 2),
    ]


def test_a_p0_outside_core_beats_a_low_priority_core_issue() -> None:
    # The regression this ordering exists for. Under the original
    # (critical, lane, prio, ...) key, lane sorted first and a core docs typo
    # dispatched ahead of a kernel security bug -- (True, 0, 3) < (True, 1, 0)
    # -- which makes prio:P0 mean "first within its lane" rather than what the
    # schema says it means.
    core_typo = QueueItem(repo="a", number=1, labels=("lane:core", "prio:P3"), age_days=1)
    kernel_p0 = QueueItem(repo="b", number=2, labels=("lane:kernel", "prio:P0"), age_days=1)
    assert sort_key(kernel_p0) < sort_key(core_typo)


def test_lane_still_decides_among_equal_priorities() -> None:
    # Lane-first was not wrong about wanting core to lead, only about letting
    # it veto. As a tiebreak within a priority, "core stays stable" survives.
    core_p0 = QueueItem(repo="z", number=9, labels=("lane:core", "prio:P0"), age_days=1)
    kernel_p0 = QueueItem(repo="a", number=1, labels=("lane:kernel", "prio:P0"), age_days=1)
    assert sort_key(core_p0) < sort_key(kernel_p0)


def test_sort_key_has_no_ties_beyond_repo_and_number() -> None:
    items = [
        QueueItem(repo="a", number=1, labels=("lane:core", "prio:P1"), age_days=3),
        QueueItem(repo="b", number=2, labels=("lane:core", "prio:P1"), age_days=3),
    ]
    keys = [sort_key(item)[:-2] for item in items]
    assert keys[0] == keys[1]  # tie on everything but the (repo, number) tail
    assert sort_key(items[0]) != sort_key(items[1])  # broken by the tail itself
