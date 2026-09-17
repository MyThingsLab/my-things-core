import json

from mythings.deps import DepEdge, DependencyGraph, collect, detect_cycles, parse_edges
from mythings.goals import IssueRef
from mythings.testing import FakeGh


def _issue(repo: str, number: int, body: str, *, state: str = "OPEN") -> IssueRef:
    return IssueRef(repo=repo, number=number, title=f"issue {number}", state=state, body=body)


# ---- marker parsing --------------------------------------------------------


def test_blocked_by_and_depends_on_markers_are_both_found() -> None:
    issue = _issue("my-fleet", 30, "Blocked by my-fleet#12.\n\nDepends on my-things-core#48.")
    edges = parse_edges(issue)
    assert {(e.kind, e.dst) for e in edges} == {
        ("blocked_by", "my-fleet#12"),
        ("depends_on", "my-things-core#48"),
    }
    assert all(e.src == "my-fleet#30" for e in edges)


def test_a_marker_without_a_number_produces_no_edge() -> None:
    # No prose fallback here -- goals.blockers() already owns fuzzy title
    # matching within one goal; fleet-wide it would only multiply ambiguity.
    issue = _issue("my-fleet", 30, "Blocked by the migration work.")
    assert parse_edges(issue) == ()


def test_a_bare_number_defaults_to_the_issues_own_repo() -> None:
    issue = _issue("my-fleet", 30, "Blocked by #12.")
    edges = parse_edges(issue)
    assert edges == (
        DepEdge(src="my-fleet#30", dst="my-fleet#12", kind="blocked_by", text="my-fleet#12"),
    )


def test_an_owner_prefix_is_kept_in_text_but_stripped_from_the_slug() -> None:
    issue = _issue("my-fleet", 30, "Depends on MyThingsLab/my-things-core#48.")
    edges = parse_edges(issue)
    assert edges[0].dst == "my-things-core#48"
    assert edges[0].text == "MyThingsLab/my-things-core#48"


def test_no_markers_at_all_produces_zero_edges() -> None:
    assert (
        parse_edges(_issue("my-fleet", 30, "Just a plain description, nothing blocking it.")) == ()
    )


# ---- blocked / ready --------------------------------------------------------


def test_blocked_and_ready_reflect_whether_the_dst_is_still_open() -> None:
    a = _issue("r", 1, "Blocked by r#2.")
    b = _issue("r", 2, "", state="OPEN")
    c = _issue("r", 3, "Blocked by r#4.")
    d = _issue("r", 4, "", state="CLOSED")
    e = _issue("r", 5, "")
    graph = DependencyGraph(
        nodes={i.slug: i for i in (a, b, c, d, e)},
        edges=parse_edges(a) + parse_edges(c),
    )
    assert set(graph.blocked) == {"r#1"}  # r#2 is open
    # r#2 names no blocker of its own; r#3's blocker (r#4) is closed; r#5 names none.
    assert set(graph.ready) == {"r#2", "r#3", "r#5"}


def test_an_edge_to_a_dst_outside_the_fetched_set_is_kept_not_dropped() -> None:
    a = _issue("r", 1, "Blocked by other#99.")
    graph = DependencyGraph(nodes={a.slug: a}, edges=parse_edges(a))
    assert graph.edges[0].dst == "other#99"
    assert "other#99" not in graph.nodes
    # Fail closed: an unresolved dst is treated as still blocking, same rule
    # goals.py uses for an ambiguous blocker clause.
    assert graph.blocked == ("r#1",)


# ---- cycle detection --------------------------------------------------------


def test_a_real_cycle_is_flagged_not_resolved() -> None:
    a = _issue("r", 1, "Blocked by r#2.")
    b = _issue("r", 2, "Blocked by r#1.")
    edges = parse_edges(a) + parse_edges(b)
    cycles = detect_cycles(edges)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"r#1", "r#2"}


def test_no_cycle_among_acyclic_edges() -> None:
    a = _issue("r", 1, "Blocked by r#2.")
    b = _issue("r", 2, "")
    assert detect_cycles(parse_edges(a) + parse_edges(b)) == ()


# ---- collection over the gh boundary ---------------------------------------


def _fake() -> FakeGh:
    fleet_issues = json.dumps(
        [
            {
                "number": 30,
                "title": "fleet thing",
                "body": "Depends on my-things-core#48.",
                "labels": [],
                "state": "OPEN",
                "url": "u",
                "closedAt": "",
            }
        ]
    )
    core_issues = json.dumps(
        [
            {
                "number": 48,
                "title": "core thing",
                "body": "",
                "labels": [],
                "state": "CLOSED",
                "url": "u",
                "closedAt": "2026-09-01T00:00:00Z",
            }
        ]
    )

    def by_repo(argv: list[str]) -> str:
        repo = argv[argv.index("--repo") + 1]
        return fleet_issues if repo.endswith("my-fleet") else core_issues

    return FakeGh({("issue", "list"): by_repo})


def test_collect_builds_cross_repo_edges() -> None:
    graph = collect(["MyThingsLab/my-fleet", "MyThingsLab/my-things-core"], runner=_fake())
    assert set(graph.nodes) == {"my-fleet#30", "my-things-core#48"}
    assert graph.edges == (
        DepEdge(
            src="my-fleet#30", dst="my-things-core#48", kind="depends_on", text="my-things-core#48"
        ),
    )
    # The dependency is closed, so nothing is actually blocked.
    assert graph.blocked == ()
    assert graph.ready == ("my-fleet#30",)


def test_an_unreachable_repo_renders_as_absent_never_as_zero() -> None:
    def boom(argv: list[str]) -> str:
        raise RuntimeError("gh: not found")

    graph = collect(["MyThingsLab/nope"], runner=boom)
    assert graph.nodes == {}
    assert graph.edges == ()
    assert graph.cycles == ()


# ---- phases & critical path ------------------------------------------------


def test_compute_phases_layers_open_nodes_topologically() -> None:
    # Phase 0: r#1, r#2 (no blockers)
    # Phase 1: r#3 (depends on r#1)
    # Phase 2: r#4 (depends on r#3)
    i1 = _issue("r", 1, "")
    i2 = _issue("r", 2, "")
    i3 = _issue("r", 3, "Depends on r#1.")
    i4 = _issue("r", 4, "Depends on r#3.")
    nodes = {i.slug: i for i in (i1, i2, i3, i4)}
    edges = parse_edges(i3) + parse_edges(i4)

    from mythings.deps import compute_phases

    phases = compute_phases(nodes, edges)
    assert phases == (("r#1", "r#2"), ("r#3",), ("r#4",))


def test_compute_critical_path_finds_longest_weighted_path() -> None:
    i1 = IssueRef(repo="r", number=1, title="root", labels=("size:S",))  # weight 1
    i2 = IssueRef(
        repo="r", number=2, title="branch A", labels=("size:M",), body="Depends on r#1."
    )  # weight 3
    i3 = IssueRef(
        repo="r", number=3, title="branch B", labels=("size:L",), body="Depends on r#1."
    )  # weight 8
    i4 = IssueRef(
        repo="r", number=4, title="sink", labels=("size:S",), body="Depends on r#3."
    )  # weight 1
    nodes = {i.slug: i for i in (i1, i2, i3, i4)}
    edges = parse_edges(i2) + parse_edges(i3) + parse_edges(i4)

    from mythings.deps import compute_critical_path

    cp = compute_critical_path(nodes, edges)
    # Path r#1 -> r#3 -> r#4 has weight 1 + 8 + 1 = 10 (vs r#1 -> r#2 weight 4)
    assert cp == ("r#1", "r#3", "r#4")


def test_to_mermaid_and_to_dict() -> None:
    i1 = IssueRef(repo="r", number=1, title="base", labels=("prio:P0", "size:M", "lane:core"))
    i2 = IssueRef(
        repo="r", number=2, title="child", labels=("prio:P1", "size:S"), body="Blocked by r#1."
    )
    nodes = {i1.slug: i1, i2.slug: i2}
    edges = parse_edges(i2)
    graph = DependencyGraph(
        nodes=nodes,
        edges=edges,
        phases=(("r#1",), ("r#2",)),
        critical_path=("r#1", "r#2"),
    )

    mermaid = graph.to_mermaid()
    assert "graph TD" in mermaid
    assert "r_1" in mermaid
    assert "r_2" in mermaid
    assert "r_1 -->|blocked_by| r_2" in mermaid

    d = graph.to_dict()
    assert "nodes" in d
    assert "r#1" in d["nodes"]
    assert d["nodes"]["r#1"]["lane"] == "core"
    assert d["nodes"]["r#1"]["prio"] == "P0"
    assert d["critical_path"] == ["r#1", "r#2"]
    assert d["phases"] == [["r#1"], ["r#2"]]


