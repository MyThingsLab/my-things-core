from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mythings.github import Runner, _gh
from mythings.goals import IssueRef

EdgeKind = Literal["blocked_by", "depends_on"]

# Explicit, number-bearing markers only -- no prose fallback. goals.blockers()
# already resolves prose ("blocked on X and Y") by fuzzy title matching within
# one goal; this module is the fleet-wide, cross-repo complement, and fuzzy
# title matching across the whole org multiplies the ambiguity that already
# makes goals.py fail closed within a single milestone. A marker without a
# number here produces no edge, not a guess.
_BLOCKED_BY_RE = re.compile(r"\bblocked[-_ ]by\s*:?\s*([^\n.]+)", re.IGNORECASE)
_DEPENDS_ON_RE = re.compile(r"\bdepends\s+on\s*:?\s*([^\n.]+)", re.IGNORECASE)
_REF_RE = re.compile(r"(?:([\w.-]+)/)?([\w.-]+)?#(\d+)")

_MARKERS: tuple[tuple[EdgeKind, re.Pattern[str]], ...] = (
    ("blocked_by", _BLOCKED_BY_RE),
    ("depends_on", _DEPENDS_ON_RE),
)


@dataclass(frozen=True)
class DepEdge:
    src: str  # "repo#N"
    dst: str  # "repo#N" -- may name a node outside the fetched repo set
    kind: EdgeKind
    text: str  # the ref exactly as written (owner/repo#N kept verbatim)


_SIZE_WEIGHTS: dict[str, int] = {
    "S": 1,
    "M": 3,
    "L": 8,
}


def compute_phases(
    nodes: dict[str, IssueRef], edges: Sequence[DepEdge]
) -> tuple[tuple[str, ...], ...]:
    """Partition nodes into topological execution phases (waves).

    Phase 0 contains nodes with no active dependencies (ready to dispatch).
    Phase k+1 contains nodes whose dependencies all belong to phase <= k.
    """
    # Active incoming edges (only edges where dst is still open)
    active_incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        dst = nodes.get(edge.dst)
        if dst is None or dst.is_open:
            active_incoming[edge.src].add(edge.dst)

    # We phase all open nodes
    open_nodes = {slug for slug, issue in nodes.items() if issue.is_open}
    if not open_nodes:
        return ()

    phases: list[tuple[str, ...]] = []
    assigned: set[str] = set()
    remaining = set(open_nodes)

    # In case of cycles or external unresolvable dependencies, prevent infinite loop
    max_phases = len(open_nodes) + 1
    for _ in range(max_phases):
        if not remaining:
            break
        # Wave: nodes whose active incoming dependencies are all outside
        # open_nodes or already assigned
        current_wave = sorted(
            [node for node in remaining if not (active_incoming[node] & (remaining - {node}))]
        )
        if not current_wave:
            # Remaining nodes are locked in cycles or blocked on unresolvable external nodes
            phases.append(tuple(sorted(remaining)))
            break
        phases.append(tuple(current_wave))
        assigned.update(current_wave)
        remaining.difference_update(current_wave)

    return tuple(phases)


def compute_critical_path(
    nodes: dict[str, IssueRef], edges: Sequence[DepEdge]
) -> tuple[str, ...]:
    """Calculate the critical path (longest weighted chain of open tasks).

    Weights are derived from size facets (S=1, M=3, L=8).
    """
    open_nodes = {slug: issue for slug, issue in nodes.items() if issue.is_open}
    if not open_nodes:
        return ()

    # Build forward adjacency for active edges
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    for node in open_nodes:
        in_degree[node] = 0

    for edge in edges:
        if edge.src in open_nodes and edge.dst in open_nodes:
            # dst must complete before src can execute: edge dst -> src
            adj[edge.dst].append(edge.src)
            in_degree[edge.src] += 1

    def node_weight(slug: str) -> int:
        issue = open_nodes.get(slug)
        if not issue:
            return 1
        size = issue.facets.size or "S"
        return _SIZE_WEIGHTS.get(size, 1)

    # Dynamic programming for longest path
    dist: dict[str, int] = {node: node_weight(node) for node in open_nodes}
    prev: dict[str, str | None] = {node: None for node in open_nodes}

    # Queue of roots in dependency order
    queue = [node for node in open_nodes if in_degree[node] == 0]
    visited_count = 0

    while queue:
        curr = queue.pop(0)
        visited_count += 1
        curr_dist = dist[curr]
        for nxt in adj.get(curr, []):
            weight = node_weight(nxt)
            if curr_dist + weight > dist[nxt]:
                dist[nxt] = curr_dist + weight
                prev[nxt] = curr
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if not dist:
        return ()

    # Find terminal node with maximum distance
    end_node = max(dist, key=dist.get)
    path = []
    step: str | None = end_node
    while step is not None:
        path.append(step)
        step = prev.get(step)

    return tuple(reversed(path))


@dataclass(frozen=True)
class DependencyGraph:
    # Only nodes actually fetched. An edge's dst absent from this dict means
    # "outside the repo set we looked at", not "resolved to nothing".
    nodes: dict[str, IssueRef]
    edges: tuple[DepEdge, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()
    phases: tuple[tuple[str, ...], ...] = ()
    critical_path: tuple[str, ...] = ()

    def _incoming(self) -> dict[str, tuple[DepEdge, ...]]:
        by_src: dict[str, list[DepEdge]] = defaultdict(list)
        for edge in self.edges:
            by_src[edge.src].append(edge)
        return {src: tuple(edges) for src, edges in by_src.items()}

    def _live(self, edge: DepEdge) -> bool:
        # A dst we never fetched is unknown, not cleared -- same fail-closed
        # rule goals.py uses for an unresolved blocker clause.
        dst = self.nodes.get(edge.dst)
        return dst is None or dst.is_open

    @property
    def blocked(self) -> tuple[str, ...]:
        incoming = self._incoming()
        return tuple(
            slug
            for slug, issue in self.nodes.items()
            if issue.is_open and any(self._live(edge) for edge in incoming.get(slug, ()))
        )

    @property
    def ready(self) -> tuple[str, ...]:
        blocked = set(self.blocked)
        return tuple(
            slug for slug, issue in self.nodes.items() if issue.is_open and slug not in blocked
        )

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for slug, issue in sorted(self.nodes.items()):
            state_marker = "OPEN" if issue.is_open else "CLOSED"
            prio = issue.facets.prio or "P2"
            size = issue.facets.size or "S"
            badge = f"<code>{prio} | {size} | {state_marker}</code>"
            label = f"{slug}<br/><b>{issue.title}</b><br/>{badge}"
            safe_id = slug.replace("#", "_").replace("-", "_")
            lines.append(f'    {safe_id}["{label}"]')

        for edge in self.edges:
            src_id = edge.src.replace("#", "_").replace("-", "_")
            dst_id = edge.dst.replace("#", "_").replace("-", "_")
            lines.append(f"    {dst_id} -->|{edge.kind}| {src_id}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "nodes": {
                slug: {
                    "repo": issue.repo,
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "url": issue.url,
                    "lane": issue.facets.lane,
                    "prio": issue.facets.prio,
                    "size": issue.facets.size,
                    "kind": issue.facets.kind,
                    "is_open": issue.is_open,
                }
                for slug, issue in self.nodes.items()
            },
            "edges": [
                {"src": e.src, "dst": e.dst, "kind": e.kind, "text": e.text} for e in self.edges
            ],
            "cycles": [list(c) for c in self.cycles],
            "phases": [list(p) for p in self.phases],
            "critical_path": list(self.critical_path),
            "blocked": list(self.blocked),
            "ready": list(self.ready),
        }


def parse_edges(issue: IssueRef) -> tuple[DepEdge, ...]:
    found: list[DepEdge] = []
    for kind, marker_re in _MARKERS:
        for clause in marker_re.findall(issue.body or ""):
            for owner, repo, number in _REF_RE.findall(clause):
                repo_name = repo or issue.repo
                text = f"{(owner + '/') if owner else ''}{repo or issue.repo}#{number}"
                found.append(
                    DepEdge(src=issue.slug, dst=f"{repo_name}#{number}", kind=kind, text=text)
                )
    return tuple(found)


def detect_cycles(edges: Sequence[DepEdge]) -> tuple[tuple[str, ...], ...]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge.src].append(edge.dst)

    cycles: list[tuple[str, ...]] = []
    seen: set[frozenset[str]] = set()
    visited: set[str] = set()
    on_stack: list[str] = []
    on_stack_set: set[str] = set()

    def dfs(node: str) -> None:
        on_stack.append(node)
        on_stack_set.add(node)
        for nxt in graph.get(node, ()):
            if nxt in on_stack_set:
                cycle = tuple(on_stack[on_stack.index(nxt) :])
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif nxt not in visited:
                dfs(nxt)
        on_stack.pop()
        on_stack_set.discard(node)
        visited.add(node)

    for node in sorted(graph):
        if node not in visited:
            dfs(node)
    return tuple(cycles)


def _repo_issues(repo: str, runner: Runner) -> list[IssueRef]:
    argv = [
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--limit",
        "200",
        "--json",
        "number,title,body,labels,state,url,closedAt",
    ]
    try:
        rows = json.loads(runner(argv))
    except Exception:  # noqa: BLE001 - unreachable/malformed repo renders as absent, never as zero
        return []
    name = repo.split("/")[-1]
    return [
        IssueRef(
            repo=name,
            number=row["number"],
            title=row.get("title", ""),
            state=row.get("state", "OPEN"),
            url=row.get("url", "") or "",
            labels=tuple(lbl["name"] for lbl in row.get("labels", []) or []),
            body=row.get("body", "") or "",
            closed_at=row.get("closedAt", "") or "",
        )
        for row in rows
    ]


def collect(repos: Sequence[str], *, runner: Runner = _gh) -> DependencyGraph:
    # Repos are passed in, not discovered -- same reasoning as goals.collect:
    # which repos count is the caller's policy decision.
    nodes: dict[str, IssueRef] = {}
    for repo in repos:
        for issue in _repo_issues(repo, runner):
            nodes[issue.slug] = issue

    edges: list[DepEdge] = []
    for issue in nodes.values():
        edges.extend(parse_edges(issue))

    cycles = detect_cycles(edges)
    phases = compute_phases(nodes, edges)
    critical_path = compute_critical_path(nodes, edges)

    return DependencyGraph(
        nodes=nodes,
        edges=tuple(edges),
        cycles=cycles,
        phases=phases,
        critical_path=critical_path,
    )

