import json
from datetime import UTC, datetime, timedelta

from mythings.goals import (
    GOAL_PREFIX,
    GoalPart,
    GoalView,
    IssueRef,
    blockers,
    collect,
    parse_description,
)
from mythings.testing import FakeGh

# The real dependency structure of goal/cad-foundation as it stood on
# 2026-09-14, when every one of these nine issues carried state:blocked and
# nothing in the fleet could tell that seven of them were free to run. Kept
# verbatim -- prose included -- because the parser exists to handle exactly
# this text, and a tidied-up paraphrase would test a problem nobody has.
_REAL = [
    (
        "my-things-core",
        147,
        "CLOSED",
        "core: mythings.labels — the CAD label schema as data, plus the priority queue sort key",
        "Part of goal/cad-foundation.",
    ),
    (
        "my-things-core",
        148,
        "CLOSED",
        "core: mythings.session — TaskRecord, Verdict, GoalRecord, GoalJournalEntry",
        "Part of goal/cad-foundation.",
    ),
    (
        "my-things-core",
        149,
        "CLOSED",
        "core: milestone helpers on GitHub — create, assign, progress",
        "Part of goal/cad-foundation.",
    ),
    (
        "my-things-core",
        150,
        "OPEN",
        "core: link mythings.plan to a goal milestone",
        "Part of goal/cad-foundation. Blocked on the milestone-helpers issue.",
    ),
    (
        "my-fleet",
        25,
        "CLOSED",
        "fleet: dry-run an acceptance gate over the 29 open org PRs",
        "Part of goal/cad-foundation.",
    ),
    (
        "my-fleet",
        26,
        "OPEN",
        "fleet: myfleet.accept — the deterministic acceptance gate",
        "Part of goal/cad-foundation. Blocked on the gate dry-run issue, "
        "and on mythings.session for the Verdict type.",
    ),
    (
        "my-fleet",
        29,
        "OPEN",
        "fleet: the Foreman — refactor fleet_dispatch into a session loop over TaskRecords",
        "Part of goal/cad-foundation. Blocked on mythings.session and myfleet.accept.",
    ),
    (
        "my-fleet",
        30,
        "OPEN",
        "fleet: lane allocation and session budget",
        "Part of goal/cad-foundation. Blocked on mythings.labels and the Foreman.",
    ),
    (
        "my-coder",
        24,
        "OPEN",
        "coder: emit a TaskRecord and honour the size:S contract",
        "Part of goal/cad-foundation. Blocked on mythings.session.",
    ),
    (
        "my-orchestrator",
        25,
        "CLOSED",
        "orchestrator: rank from the CAD labels via mythings.labels.sort_key",
        "Part of goal/cad-foundation. Blocked on mythings.labels.",
    ),
    (
        "my-orchestrator",
        26,
        "OPEN",
        "orchestrator: lane freeze — red core or kernel CI halts every other lane",
        "Part of goal/cad-foundation. Blocked on the ranking issue.",
    ),
    (
        "my-architect",
        14,
        "OPEN",
        "architect: phase-scoped decomposition with a goal journal",
        "Part of goal/cad-foundation. Blocked on mythings.session.",
    ),
    (
        "my-director",
        10,
        "OPEN",
        "director: mydirector goal --new, the weekly goal interview",
        "Part of goal/cad-foundation. Blocked on mythings.session and the milestone helpers.",
    ),
    (
        "my-reporter",
        18,
        "OPEN",
        "reporter: myreporter goal — burn-down, journal digest, stall detection",
        "Part of goal/cad-foundation. Blocked on mythings.session and the milestone helpers.",
    ),
]


def _issues(*, blocked_label: bool = True) -> list[IssueRef]:
    out = []
    for repo, number, state, title, body in _REAL:
        labels = ["lane:kernel", "prio:P1", "kind:feat", "size:S"]
        if state == "OPEN":
            labels.append("state:blocked" if blocked_label else "state:ready")
        out.append(
            IssueRef(
                repo=repo,
                number=number,
                title=title,
                state=state,
                labels=tuple(labels),
                body=body,
                closed_at="2026-09-13T12:00:00Z" if state == "CLOSED" else "",
            )
        )
    return out


def _view(issues: list[IssueRef], **kw) -> GoalView:
    claimed = {
        i.slug: found
        for i in issues
        if (found := blockers(i.body, [c for c in issues if c.slug != i.slug]))
    }
    return GoalView(
        goal_id="goal/cad-foundation",
        issues=tuple(issues),
        blockers=claimed,
        **kw,
    )


# ---- blocker resolution ---------------------------------------------------


def test_the_seven_falsely_blocked_issues_are_found_and_the_two_real_ones_are_not() -> None:
    # The whole point. my-fleet#29 waits on my-fleet#26 (open) and my-fleet#30
    # waits on #29 (open), so the chain is genuinely blocked and must stay
    # that way; every other issue's blockers are closed and shipped.
    view = _view(_issues())
    assert {i.slug for i in view.falsely_blocked} == {
        "my-things-core#150",
        "my-fleet#26",
        "my-coder#24",
        "my-orchestrator#26",
        "my-architect#14",
        "my-director#10",
        "my-reporter#18",
    }
    still = {i.slug for i in view.blocked} - {i.slug for i in view.falsely_blocked}
    assert still == {"my-fleet#29", "my-fleet#30"}


def test_a_clause_naming_two_things_resolves_both() -> None:
    issues = _issues()
    found = blockers(
        "Blocked on the gate dry-run issue, and on mythings.session for the Verdict type.",
        [i for i in issues if i.slug != "my-fleet#26"],
    )
    assert [b.resolved.slug for b in found] == ["my-fleet#25", "my-things-core#148"]


def test_a_trailing_qualifier_is_not_part_of_the_name() -> None:
    # "mythings.session for the Verdict type" names mythings.session. Keeping
    # "verdict"/"type" as required tokens matched nothing at all.
    found = blockers("Blocked on mythings.session for the Verdict type.", _issues())
    assert len(found) == 1
    assert found[0].resolved is not None
    assert found[0].resolved.number == 148


def test_ranking_resolves_to_rank_without_a_stemmer() -> None:
    found = blockers("Blocked on the ranking issue.", _issues())
    assert found[0].resolved is not None
    assert found[0].resolved.slug == "my-orchestrator#25"


def test_an_open_blocker_does_not_clear() -> None:
    found = blockers("Blocked on mythings.session and myfleet.accept.", _issues())
    assert [b.cleared for b in found] == [True, False]


def test_an_ambiguous_clause_resolves_to_nothing_and_stays_blocked() -> None:
    # "session" alone matches mythings.session, the Foreman's session loop and
    # lane allocation's session budget. Guessing between three is exactly the
    # judgement this module refuses to make.
    found = blockers("Blocked on session.", _issues())
    assert found[0].resolved is None
    assert found[0].cleared is False


def test_an_issue_naming_no_blocker_is_never_unblocked() -> None:
    # A bare state:blocked label with no claim in the body is the label being
    # the only evidence, so the label wins.
    issues = [
        IssueRef(
            repo="r",
            number=1,
            title="t",
            state="OPEN",
            labels=("state:blocked",),
            body="no claim here",
        ),
    ]
    view = _view(issues)
    assert view.blocked
    assert view.falsely_blocked == ()


def test_the_structured_form_wins_over_prose_in_the_same_body() -> None:
    issues = _issues()
    found = blockers(
        "blocked-by: my-things-core#148\n\nBlocked on the Foreman as well, informally.",
        issues,
    )
    assert [b.text for b in found] == ["my-things-core#148"]
    assert found[0].cleared is True


def test_a_structured_ref_to_an_unknown_issue_does_not_clear() -> None:
    found = blockers("blocked-by: my-fleet#9999", _issues())
    assert found[0].resolved is None
    assert found[0].cleared is False


# ---- description parsing --------------------------------------------------


def test_the_real_milestone_description_yields_a_done_when() -> None:
    statement, done_when, phases = parse_description(
        "done_when: `myfleet accept --pr <n>` returns a Verdict for all 29 open org PRs.\n"
        "Week of 2026-09-12 -> 2026-09-18."
    )
    assert done_when == ("`myfleet accept --pr <n>` returns a Verdict for all 29 open org PRs.",)
    assert statement == "Week of 2026-09-12 -> 2026-09-18."
    assert phases == ()


def test_phases_parse_from_either_form_and_keep_their_order() -> None:
    _, _, numbered = parse_description("phase 2: build it\nphase 1: design it")
    assert numbered == ("design it", "build it")
    _, _, piped = parse_description("phases: design it | build it | ship it")
    assert piped == ("design it", "build it", "ship it")


def test_an_empty_description_is_absent_not_invented() -> None:
    assert parse_description("") == ("", (), ())


# ---- verdict --------------------------------------------------------------

_NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _dated(state: str, days_ago: float) -> IssueRef:
    closed = (_NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return IssueRef(
        repo="r",
        number=int(days_ago * 100) + (0 if state == "CLOSED" else 1),
        title="t",
        state=state,
        labels=("state:ready",),
        closed_at=closed if state == "CLOSED" else "",
    )


def test_a_goal_with_nothing_open_is_met() -> None:
    view = _view([_dated("CLOSED", 1)])
    assert view.verdict(now=_NOW) == "met"


def test_a_goal_whose_every_open_issue_is_blocked_is_blocked_not_at_risk() -> None:
    # The failure this seam was built for: arithmetic says 68% and five days
    # left, which reads as merely tight. Nothing was dispatchable at all.
    view = _view(_issues(), due_on="2026-09-18T00:00:00Z")
    assert view.verdict(now=_NOW) == "blocked"


def test_a_goal_with_no_closure_in_two_weeks_is_stalled() -> None:
    view = _view([_dated("CLOSED", 30), _dated("OPEN", 0)], due_on="2026-12-01T00:00:00Z")
    assert view.verdict(now=_NOW) == "stalled"


def test_a_goal_closing_too_slowly_for_its_due_date_is_at_risk() -> None:
    issues = [_dated("CLOSED", 10)] + [_dated("OPEN", n) for n in range(1, 9)]
    view = _view(issues, due_on=(_NOW + timedelta(days=2)).isoformat())
    assert view.verdict(now=_NOW) == "at_risk"


def test_a_goal_closing_fast_enough_is_on_track() -> None:
    issues = [_dated("CLOSED", n) for n in range(1, 9)] + [_dated("OPEN", 0)]
    view = _view(issues, due_on=(_NOW + timedelta(days=30)).isoformat())
    assert view.verdict(now=_NOW) == "on_track"


def test_a_goal_with_no_due_date_is_never_at_risk() -> None:
    issues = [_dated("CLOSED", 1)] + [_dated("OPEN", n) for n in range(1, 20)]
    assert _view(issues).verdict(now=_NOW) == "on_track"


# ---- the agent-facing brief ----------------------------------------------


def test_the_brief_carries_the_oracle_the_peers_and_the_dead_ends() -> None:
    view = _view(
        _issues(blocked_label=False),
        statement="Close the CAD loop.",
        done_when=("`myfleet accept --pr <n>` returns a Verdict",),
        phases=("design", "build"),
        due_on="2026-09-18T00:00:00Z",
    )
    brief = view.brief(for_repo="my-coder", dead_ends=["paths-ignore deadlocks required checks"])
    assert "goal/cad-foundation" in brief
    assert "Close the CAD loop." in brief
    assert "`myfleet accept --pr <n>` returns a Verdict" in brief
    assert "1. design" in brief
    assert "paths-ignore deadlocks required checks" in brief
    # Already-landed work, so a worker builds on it instead of rebuilding it.
    assert "my-things-core#148" in brief


def test_the_brief_omits_the_reader_own_repo_from_the_peer_list() -> None:
    view = _view(_issues(blocked_label=False))
    brief = view.brief(for_repo="my-coder")
    peers = brief.split("**Sibling work in this goal, not yours to do:**")[1]
    peers = peers.split("**Already landed")[0]
    assert "my-coder#24" not in peers
    assert "my-fleet#26" in peers


# ---- collection over the gh boundary -------------------------------------


def _fake() -> FakeGh:
    milestones = json.dumps(
        [
            {
                "title": "goal/cad-foundation",
                "description": "done_when: the loop closes.",
                "due_on": "2026-09-18T00:00:00Z",
                "open_issues": 1,
                "closed_issues": 1,
                "html_url": "https://example/m",
            },
            {"title": "v2 cleanup", "description": "", "open_issues": 3, "closed_issues": 0},
        ]
    )
    issues = json.dumps(
        [
            {
                "number": 148,
                "title": "core: mythings.session — TaskRecord",
                "body": "",
                "labels": [],
                "state": "CLOSED",
                "url": "u",
                "closedAt": "2026-09-13T12:00:00Z",
            },
            {
                "number": 150,
                "title": "core: link mythings.plan to a goal milestone",
                "body": "Blocked on mythings.session.",
                "labels": [{"name": "state:blocked"}],
                "state": "OPEN",
                "url": "u",
                "closedAt": "",
            },
        ]
    )
    return FakeGh({("api",): milestones, ("issue", "list"): issues})


def test_collect_reads_only_goal_prefixed_milestones() -> None:
    views = collect(["MyThingsLab/my-things-core"], runner=_fake())
    assert [v.goal_id for v in views] == ["goal/cad-foundation"]
    assert views[0].done_when == ("the loop closes.",)
    assert views[0].slug == "cad-foundation"


def test_collect_joins_blockers_across_the_milestone() -> None:
    view = collect(["MyThingsLab/my-things-core"], runner=_fake())[0]
    assert [i.slug for i in view.falsely_blocked] == ["my-things-core#150"]
    assert view.progress() == (1, 2)


def test_an_unreachable_repo_renders_as_absent_never_as_zero() -> None:
    def boom(argv: list[str]) -> str:
        raise RuntimeError("gh: not found")

    assert collect(["MyThingsLab/nope"], runner=boom) == ()


def test_a_goal_spanning_repos_takes_the_longest_description() -> None:
    # The same goal is milestoned in every repo it touches; the later ones are
    # usually created with a stub or nothing at all.
    def runner(argv: list[str]) -> str:
        if argv[0] == "api":
            full = "my-things-core" in argv[1]
            return json.dumps(
                [
                    {
                        "title": "goal/x",
                        "description": "done_when: everything works." if full else "",
                        "open_issues": 0,
                        "closed_issues": 0,
                    }
                ]
            )
        return "[]"

    views = collect(["MyThingsLab/my-fleet", "MyThingsLab/my-things-core"], runner=runner)
    assert views[0].done_when == ("everything works.",)
    assert [p.repo for p in views[0].parts] == ["my-fleet", "my-things-core"]


def test_goal_prefix_is_the_whole_mechanism() -> None:
    assert GOAL_PREFIX == "goal/"
    assert GoalPart(repo="r", open_issues=2, closed_issues=3).total == 5
