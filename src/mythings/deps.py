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


@dataclass(frozen=True)
class DependencyGraph:
    # Only nodes actually fetched. An edge's dst absent from this dict means
    # "outside the repo set we looked at", not "resolved to nothing".
    nodes: dict[str, IssueRef]
    edges: tuple[DepEdge, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()

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

    return DependencyGraph(nodes=nodes, edges=tuple(edges), cycles=detect_cycles(edges))
