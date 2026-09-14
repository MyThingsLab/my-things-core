"""Deterministic property graph for code, documentation, and CAD ephemeral worker context.

Provides:
- SQLite-backed relational property graph (nodes and edges) with recursive CTE traversals.
- Deterministic Python AST extractor (modules, classes, functions, calls, imports, types).
- Deterministic Markdown extractor (headings, sections, ADRs, backtick symbol links).
- Agent Context Pack (ACP) generator to constrain ephemeral agent blast radius.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Bump whenever the extractor's edge format or the traversal rules change, so a
# cache written by an older version is not silently reused. The fleet keys its
# `.mythings/graph.sqlite` cache on the repo's commit SHA alone, so a repo whose
# HEAD has not moved keeps serving edges the current traversal no longer
# understands -- and the symptom is an Agent Context Pack that reports no
# callers and no tests, which reads as a real answer.
GRAPH_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Node:
    """A node in the codebase property graph."""

    id: str
    kind: str  # module, class, function, method, type, doc_page, doc_section, invariant, adr
    name: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None


@dataclass(frozen=True)
class Edge:
    """A directed edge in the codebase property graph."""

    source_id: str
    target_id: str
    kind: str
    # kinds: contains, imports, calls, references_type, inherits, implements,
    #        documents, governs, satisfies
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlastRadius:
    """Deterministic blast radius around a seed symbol."""

    seed_id: str
    focus_node: Node | None
    upstream_callers: list[Node] = field(default_factory=list)
    downstream_callees: list[Node] = field(default_factory=list)
    types: list[Node] = field(default_factory=list)
    tests: list[Node] = field(default_factory=list)
    invariants: list[Node] = field(default_factory=list)
    docs: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class CloneGroup:
    """A set of duplicate or near-duplicate function/method nodes."""

    hash_value: str
    clone_type: Literal["exact", "structural"]
    nodes: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class TestGap:
    """A production symbol with dependent callers but zero direct tests."""

    symbol: Node
    caller_count: int
    callers: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class UntestedInvariant:
    """An ADR or Invariant specification whose governed code symbols lack test verification."""

    invariant: Node
    governed_symbols: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class CircularImport:
    """A detected cyclic import path between modules."""

    cycle: list[str]  # e.g. ["module:a", "module:b", "module:a"]


class CodebaseGraph:
    """SQLite-backed deterministic property graph."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path) if db_path is not None else ":memory:"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    @classmethod
    def in_memory(cls) -> CodebaseGraph:
        return cls(":memory:")

    @classmethod
    def open_cached(cls, db_path: str | Path) -> CodebaseGraph | None:
        """Open a persisted graph, or None if it is absent or written by another schema version."""
        # Every consumer reaches for a cache and falls back to indexing when
        # there isn't one. Deciding "is this cache usable" here means none of
        # them has to re-derive the rule -- two of the three never checked
        # anything beyond the file existing.
        path = Path(db_path)
        if not path.exists():
            return None
        probe = sqlite3.connect(str(path))
        try:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError:
            return None
        finally:
            probe.close()
        if version != GRAPH_SCHEMA_VERSION:
            return None
        return cls(path)

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    start_line INTEGER,
                    end_line INTEGER,
                    metadata_json TEXT NOT NULL,
                    content_hash TEXT
                );

                CREATE TABLE IF NOT EXISTS edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, kind),
                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
                CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
                CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);

                -- The AST extractor cannot resolve a bare `foo()` call to a
                -- definition, so it emits the unresolved target `symbol:foo`.
                -- Traversals then "resolve" those by name -- which is only
                -- sound when exactly one definition owns the name. With 19
                -- functions called `main`, a bare `symbol:main` target links
                -- every one of them to every caller of any other, so a blast
                -- radius leaks across unrelated modules. This view is the
                -- single place that decides a name is unambiguous enough to
                -- traverse; ambiguous names stay unresolved, which is the
                -- honest answer.
                CREATE VIEW IF NOT EXISTS resolvable_names AS
                SELECT name, MIN(id) AS node_id
                FROM nodes
                WHERE kind IN ('function', 'method', 'class')
                GROUP BY name
                HAVING COUNT(*) = 1;
                """
            )
            # PRAGMA takes no parameters, and the value is a module constant.
            self.conn.execute(f"PRAGMA user_version = {GRAPH_SCHEMA_VERSION:d}")

    def _refresh_resolution_index(self) -> None:
        # `resolvable_names` is a view over a GROUP BY, so a traversal that
        # correlates against it on `node_id` (an aggregate output, not the
        # grouping key) makes SQLite re-aggregate the whole nodes table once per
        # row -- quadratic, and measurably ~450x slower on the recursive caller
        # walk. Materialise the same answer once per traversal into an indexed
        # temp table so each lookup is an index seek.
        #
        # Built with plain execute() rather than executescript(): the latter
        # issues an implicit COMMIT, which fails with "database table is
        # locked" whenever the caller is iterating a cursor on this same
        # connection -- `for row in conn.execute(...): graph.blast_radius(...)`
        # is the obvious way to use this API, so it must not crash. For the
        # same reason the table is emptied and refilled rather than dropped.
        self.conn.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS resolved_symbol
            (node_id TEXT PRIMARY KEY, sym TEXT)
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS temp.idx_resolved_sym ON resolved_symbol(sym)"
        )
        self.conn.execute("DELETE FROM resolved_symbol")
        self.conn.execute(
            """
            INSERT INTO resolved_symbol (node_id, sym)
            SELECT node_id, 'symbol:' || name FROM resolvable_names
            """
        )

    def add_node(self, node: Node) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO nodes
                (id, kind, name, path, start_line, end_line, metadata_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.kind,
                    node.name,
                    node.path,
                    node.start_line,
                    node.end_line,
                    json.dumps(node.metadata),
                    node.content_hash,
                ),
            )

    def add_nodes(self, nodes: Iterable[Node]) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO nodes
                (id, kind, name, path, start_line, end_line, metadata_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        n.id,
                        n.kind,
                        n.name,
                        n.path,
                        n.start_line,
                        n.end_line,
                        json.dumps(n.metadata),
                        n.content_hash,
                    )
                    for n in nodes
                ],
            )

    def add_edge(self, edge: Edge) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO edges
                (source_id, target_id, kind, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    edge.source_id,
                    edge.target_id,
                    edge.kind,
                    json.dumps(edge.metadata),
                ),
            )

    def add_edges(self, edges: Iterable[Edge]) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO edges
                (source_id, target_id, kind, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        e.source_id,
                        e.target_id,
                        e.kind,
                        json.dumps(e.metadata),
                    )
                    for e in edges
                ],
            )

    def _row_to_node(self, row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            path=row["path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            content_hash=row["content_hash"],
        )

    def _row_to_edge(self, row: sqlite3.Row) -> Edge:
        return Edge(
            source_id=row["source_id"],
            target_id=row["target_id"],
            kind=row["kind"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )

    def get_node(self, node_id: str) -> Node | None:
        cur = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cur.fetchone()
        return self._row_to_node(row) if row else None

    def get_nodes_by_path(self, path: str) -> list[Node]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE path = ?", (path,))
        return [self._row_to_node(r) for r in cur.fetchall()]

    def get_nodes_by_kind(self, kind: str) -> list[Node]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE kind = ?", (kind,))
        return [self._row_to_node(r) for r in cur.fetchall()]

    def find_symbols(self, name: str) -> list[Node]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE name = ?", (name,))
        return [self._row_to_node(r) for r in cur.fetchall()]

    def neighbors(
        self,
        node_id: str,
        direction: Literal["both", "in", "out"] = "both",
        edge_kinds: Sequence[str] | None = None,
    ) -> list[Node]:
        """Find immediate 1-hop neighbors of a node."""
        kind_clause = ""
        params: list[Any] = []
        if edge_kinds:
            placeholders = ",".join("?" for _ in edge_kinds)
            kind_clause = f"AND e.kind IN ({placeholders})"
            params.extend(edge_kinds)

        if direction == "out":
            query = f"""
                SELECT DISTINCT n.* FROM nodes n
                JOIN edges e ON n.id = e.target_id
                WHERE e.source_id = ? {kind_clause}
            """
            cur = self.conn.execute(query, [node_id, *params])
        elif direction == "in":
            query = f"""
                SELECT DISTINCT n.* FROM nodes n
                JOIN edges e ON n.id = e.source_id
                WHERE e.target_id = ? {kind_clause}
            """
            cur = self.conn.execute(query, [node_id, *params])
        else:
            query = f"""
                SELECT DISTINCT n.* FROM nodes n
                JOIN edges e ON (n.id = e.target_id AND e.source_id = ?)
                WHERE 1=1 {kind_clause}
                UNION
                SELECT DISTINCT n.* FROM nodes n
                JOIN edges e ON (n.id = e.source_id AND e.target_id = ?)
                WHERE 1=1 {kind_clause}
            """
            cur = self.conn.execute(query, [node_id, *params, node_id, *params])

        return [self._row_to_node(r) for r in cur.fetchall()]

    def k_hop_subgraph(
        self,
        seed_ids: Sequence[str],
        k: int = 1,
        edge_kinds: Sequence[str] | None = None,
    ) -> tuple[list[Node], list[Edge]]:
        """Compute the k-hop neighborhood around seed nodes using recursive CTE."""
        if not seed_ids:
            return [], []

        kind_filter = ""
        params: list[Any] = list(seed_ids)
        if edge_kinds:
            placeholders = ",".join("?" for _ in edge_kinds)
            kind_filter = f"AND e.kind IN ({placeholders})"

        seed_placeholders = ",".join("?" for _ in seed_ids)
        query = f"""
        WITH RECURSIVE reachable(node_id, depth) AS (
            SELECT id, 0 FROM nodes WHERE id IN ({seed_placeholders})
            UNION
            SELECT
                CASE WHEN e.source_id = r.node_id THEN e.target_id ELSE e.source_id END,
                r.depth + 1
            FROM edges e
            JOIN reachable r ON (e.source_id = r.node_id OR e.target_id = r.node_id)
            WHERE r.depth < ? {kind_filter}
        )
        SELECT DISTINCT n.* FROM nodes n
        JOIN reachable r ON n.id = r.node_id
        """
        all_params = [*params, k]
        if edge_kinds:
            all_params.extend(edge_kinds)

        cur = self.conn.execute(query, all_params)
        nodes = [self._row_to_node(r) for r in cur.fetchall()]
        node_ids = {n.id for n in nodes}

        if not node_ids:
            return [], []

        node_placeholders = ",".join("?" for _ in node_ids)
        edge_query = f"""
            SELECT * FROM edges
            WHERE source_id IN ({node_placeholders})
              AND target_id IN ({node_placeholders})
        """
        edge_cur = self.conn.execute(edge_query, [*list(node_ids), *list(node_ids)])
        edges = [self._row_to_edge(r) for r in edge_cur.fetchall()]
        return nodes, edges

    def blast_radius(self, seed_id: str) -> BlastRadius:
        """Compute the deterministic blast radius for an edit to seed_id."""
        self._refresh_resolution_index()
        focus = self.get_node(seed_id)

        # The seed itself gets the same ambiguity guard as every recursive hop:
        # widening the search to `symbol:NAME` is only sound when NAME has one
        # definition and that definition is the seed. Otherwise the short seed
        # collapses to the exact id and the unresolved callers stay unclaimed.
        short_seed = seed_id
        if focus is not None:
            row = self.conn.execute(
                "SELECT sym FROM resolved_symbol WHERE node_id = ?", (focus.id,)
            ).fetchone()
            if row:
                short_seed = row[0]

        # 1. Upstream callers (reverse calls transitive closure up to 3 hops)
        # The recursive step may only follow an unresolved `symbol:NAME` target
        # when that name has exactly one definition (see resolvable_names).
        caller_query = """
        WITH RECURSIVE upstream(id, depth) AS (
            SELECT source_id, 1 FROM edges
            WHERE (target_id = ? OR target_id = ?) AND kind = 'calls'
            UNION
            SELECT e.source_id, u.depth + 1
            FROM edges e
            JOIN upstream u ON (
                e.target_id = u.id
                OR e.target_id = (SELECT rs.sym FROM resolved_symbol rs
                                  WHERE rs.node_id = u.id)
            )
            WHERE e.kind = 'calls' AND u.depth < 3
        )
        SELECT DISTINCT n.* FROM nodes n
        JOIN upstream u ON n.id = u.id
        ORDER BY n.path, n.start_line, n.id
        """
        callers = [
            self._row_to_node(r)
            for r in self.conn.execute(caller_query, (seed_id, short_seed)).fetchall()
        ]

        # 2. Downstream callees (1 hop calls)
        callee_query = """
        SELECT DISTINCT n.* FROM nodes n
        JOIN edges e ON (
            n.id = e.target_id
            OR e.target_id = (SELECT rs.sym FROM resolved_symbol rs
                              WHERE rs.node_id = n.id)
        )
        WHERE e.source_id = ? AND e.kind = 'calls'
        ORDER BY n.path, n.start_line, n.id
        """
        callees = [
            self._row_to_node(r) for r in self.conn.execute(callee_query, (seed_id,)).fetchall()
        ]

        # 3. Types referenced (1 hop)
        type_query = """
        SELECT DISTINCT n.* FROM nodes n
        JOIN edges e ON n.id = e.target_id
        WHERE e.source_id = ? AND e.kind = 'references_type'
        ORDER BY n.path, n.start_line, n.id
        """
        types = [self._row_to_node(r) for r in self.conn.execute(type_query, (seed_id,)).fetchall()]

        # 4. Tests covering the symbol -- callers that are themselves tests.
        tests = [c for c in callers if self._is_test_node(c)]

        # 5. Invariants and ADRs governing this node or its module
        # Find doc nodes connected via governs, satisfies, or documents
        doc_query = """
        SELECT DISTINCT n.* FROM nodes n
        JOIN edges e ON (n.id = e.source_id AND e.target_id = ?)
                     OR (n.id = e.target_id AND e.source_id = ?)
        WHERE e.kind IN ('documents', 'governs', 'satisfies')
        """
        doc_nodes = [
            self._row_to_node(r)
            for r in self.conn.execute(doc_query, (seed_id, seed_id)).fetchall()
        ]
        invariants = [d for d in doc_nodes if d.kind in ("invariant", "adr")]
        docs = [d for d in doc_nodes if d.kind not in ("invariant", "adr")]

        return BlastRadius(
            seed_id=seed_id,
            focus_node=focus,
            upstream_callers=callers,
            downstream_callees=callees,
            types=types,
            tests=tests,
            invariants=invariants,
            docs=docs,
        )

    def _callers_of(self, node: Node) -> list[Node]:
        # Exact-id callers, plus callers of the unresolved `symbol:NAME` target
        # but only when NAME is unambiguous. Without that guard a single tested
        # `run` launders coverage onto all 22 functions sharing the name.
        callers = self.neighbors(node.id, direction="in", edge_kinds=["calls"])
        seen = {c.id for c in callers}
        resolvable = self.conn.execute(
            "SELECT sym FROM resolved_symbol WHERE node_id = ?", (node.id,)
        ).fetchone()
        if resolvable:
            rows = self.conn.execute(
                """
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.source_id
                WHERE e.target_id = ? AND e.kind = 'calls'
                """,
                (resolvable[0],),
            ).fetchall()
            for r in rows:
                c_node = self._row_to_node(r)
                if c_node.id not in seen:
                    seen.add(c_node.id)
                    callers.append(c_node)
        callers.sort(key=lambda c: (c.path, c.start_line or 0, c.id))
        return callers

    @staticmethod
    def _is_test_node(node: Node) -> bool:
        # `test_*.py` and `*_test.py` are both pytest defaults; missing the
        # second one would report a covered symbol as a test gap.
        filename = Path(node.path).name
        return (
            node.name.startswith("test_")
            or node.path.startswith("tests/")
            or "/tests/" in node.path
            or filename.startswith("test_")
            or filename.endswith("_test.py")
        )

    def find_structural_clones(self, min_lines: int = 3) -> list[CloneGroup]:
        """Discover exact and AST structural code clones across functions and methods."""
        query = """
        SELECT * FROM nodes
        WHERE kind IN ('function', 'method')
          AND (end_line - start_line + 1) >= ?
        """
        rows = self.conn.execute(query, (min_lines,)).fetchall()
        nodes = [self._row_to_node(r) for r in rows]

        exact_groups: dict[str, list[Node]] = {}
        for n in nodes:
            if n.content_hash:
                exact_groups.setdefault(n.content_hash, []).append(n)

        shape_groups: dict[str, list[Node]] = {}
        for n in nodes:
            s_hash = n.metadata.get("shape_hash")
            if s_hash:
                shape_groups.setdefault(s_hash, []).append(n)

        results: list[CloneGroup] = []
        seen_node_sets: set[frozenset[str]] = set()

        for chash, grp in exact_groups.items():
            if len(grp) >= 2:
                results.append(CloneGroup(hash_value=chash, clone_type="exact", nodes=grp))
                seen_node_sets.add(frozenset(n.id for n in grp))

        for shash, grp in shape_groups.items():
            if len(grp) >= 2:
                ids = frozenset(n.id for n in grp)
                if ids not in seen_node_sets:
                    results.append(CloneGroup(hash_value=shash, clone_type="structural", nodes=grp))

        return results

    def find_test_gaps(self, min_callers: int = 1) -> list[TestGap]:
        """Identify production symbols with dependent callers but zero direct tests."""
        self._refresh_resolution_index()
        # Predicates over names stay in Python. `_` is a single-character LIKE
        # wildcard, so SQL spellings of them silently over-match: a
        # `NOT LIKE '%_test.py'` meant to skip `parser_test.py` also swallowed
        # `latest.py`, and a `LIKE '__%__'` meant to skip dunder methods matched
        # `close`, `record` and every other method name of four or more
        # characters -- 179 of this repo's 195 methods, none of which were ever
        # considered for a test gap.
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE kind IN ('function', 'method')"
        ).fetchall()
        prod_nodes = [
            n
            for n in (self._row_to_node(r) for r in rows)
            if not self._is_test_node(n) and not (n.kind == "method" and _is_dunder(n.name))
        ]

        gaps: list[TestGap] = []
        for n in prod_nodes:
            callers = self._callers_of(n)
            if len(callers) < min_callers:
                continue
            if not any(self._is_test_node(c) for c in callers):
                gaps.append(TestGap(symbol=n, caller_count=len(callers), callers=callers))

        gaps.sort(key=lambda g: (-g.caller_count, g.symbol.path, g.symbol.id))
        return gaps

    def find_untested_invariants(self) -> list[UntestedInvariant]:
        """Find ADR and Invariant documentation nodes whose governed symbols lack test coverage."""
        self._refresh_resolution_index()
        query = """
        SELECT * FROM nodes
        WHERE kind IN ('invariant', 'adr')
        """
        doc_rows = self.conn.execute(query).fetchall()
        invariants = [self._row_to_node(r) for r in doc_rows]

        untested: list[UntestedInvariant] = []
        for inv in invariants:
            sym_query = """
            SELECT DISTINCT n.* FROM nodes n
            JOIN edges e ON (
                (
                    n.id = e.target_id
                    OR (e.target_id LIKE 'symbol:%' AND n.name = SUBSTR(e.target_id, 8))
                )
                AND e.source_id = ?
            ) OR (
                (
                    n.id = e.source_id
                    OR (e.source_id LIKE 'symbol:%' AND n.name = SUBSTR(e.source_id, 8))
                )
                AND e.target_id = ?
            )
            WHERE e.kind IN ('governs', 'satisfies', 'documents')
              AND n.kind IN ('function', 'method', 'class')
            """
            sym_rows = self.conn.execute(sym_query, (inv.id, inv.id)).fetchall()
            governed = [self._row_to_node(r) for r in sym_rows]
            if not governed:
                continue

            any_tested = False
            for s in governed:
                if any(self._is_test_node(c) for c in self._callers_of(s)):
                    any_tested = True
                    break

            if not any_tested:
                untested.append(UntestedInvariant(invariant=inv, governed_symbols=governed))

        return untested

    def find_circular_imports(self) -> list[list[str]]:
        """Detect circular module dependencies across imports edges."""
        # A deferred (function-local) import does not run at import time, so it
        # cannot form an import cycle -- reporting one would flag the very
        # workaround that prevents it.
        query = """
        SELECT DISTINCT source_id, target_id FROM edges
        WHERE kind = 'imports' AND source_id LIKE 'module:%'
          AND json_extract(metadata_json, '$.deferred') IS NULL
        """
        rows = self.conn.execute(query).fetchall()
        adj: dict[str, set[str]] = {}
        for src, tgt in rows:
            tgt_mod = (
                tgt
                if tgt.startswith("module:")
                else f"module:{tgt.split('symbol:')[-1].rsplit('.', 1)[0]}"
            )
            if src != tgt_mod:
                adj.setdefault(src, set()).add(tgt_mod)

        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: list[str] = []
        stack_set: set[str] = set()

        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            stack_set.add(node)

            for neighbor in adj.get(node, ()):
                if neighbor in stack_set:
                    idx = stack.index(neighbor)
                    cycles.append(stack[idx:] + [neighbor])
                elif neighbor not in visited:
                    dfs(neighbor)

            stack.pop()
            stack_set.remove(node)

        for node in list(adj.keys()):
            if node not in visited:
                dfs(node)

        unique_cycles: list[list[str]] = []
        seen_representations: set[str] = set()
        for c in cycles:
            core = c[:-1]
            if not core:
                continue
            min_idx = core.index(min(core))
            norm = tuple(core[min_idx:] + core[:min_idx])
            rep = "->".join(norm)
            if rep not in seen_representations:
                seen_representations.add(rep)
                unique_cycles.append(list(norm) + [norm[0]])

        return unique_cycles

    def find_unreferenced_symbols(self) -> list[Node]:
        """Identify internal/private symbols with zero incoming code or documentation edges."""
        # The bare-name fallback below is deliberately *not* narrowed the way
        # the traversals are. There, an unresolved `symbol:run` matching all 50
        # `run`s invents callers; here it only ever suppresses a report, and the
        # report is "this is dead, delete it". Over-suppressing costs nothing;
        # under-suppressing tells an agent to delete live code.
        query = """
        SELECT n.* FROM nodes n
        WHERE n.kind IN ('function', 'method', 'class')
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE (
                  e.target_id = n.id
                  OR (e.target_id LIKE 'symbol:%' AND n.name = SUBSTR(e.target_id, 8))
              )
              AND e.kind != 'contains'
          )
        """
        rows = self.conn.execute(query).fetchall()
        # `name LIKE '_%'` did not mean "starts with an underscore" -- `_` is a
        # wildcard, so it matched every symbol, and this returned public API as
        # dead code.
        return [
            n
            for n in (self._row_to_node(r) for r in rows)
            if n.name.startswith("_")
            and not (n.kind == "method" and _is_dunder(n.name))
            and not self._is_test_node(n)
        ]


def _compute_ast_shape_hash(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Compute a structural hash of function AST, normalizing variable names and docstrings."""
    body = fn_node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    class Normalizer(ast.NodeTransformer):
        def __init__(self) -> None:
            self.var_map: dict[str, str] = {}
            self.counter = 0

        def _get_var(self, name: str) -> str:
            if name.startswith("__") and name.endswith("__"):
                return name
            if name not in self.var_map:
                self.var_map[name] = f"v_{self.counter}"
                self.counter += 1
            return self.var_map[name]

        def visit_Name(self, n: ast.Name) -> ast.Name:
            return ast.Name(id=self._get_var(n.id), ctx=n.ctx)

        def visit_arg(self, a: ast.arg) -> ast.arg:
            return ast.arg(arg=self._get_var(a.arg), annotation=None)

    copied = copy.deepcopy(fn_node)
    copied.name = "fn"
    copied.body = copy.deepcopy(body)
    copied.returns = None
    copied.decorator_list = []
    normalized = Normalizer().visit(copied)
    dumped = ast.dump(normalized, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]


DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "build",
    "dist",
    ".claude",
    ".mythings",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
)


def _iter_repo_files(root: Path, pattern: str, excludes: Sequence[str]) -> list[Path]:
    # Sorted, so indexing order does not depend on filesystem readdir order --
    # the graph is only reproducible across machines if this is.
    nested_cache: dict[Path, bool] = {}

    def in_nested_checkout(directory: Path) -> bool:
        # A repo that has git worktrees nested inside it (this fleet nests one
        # per sibling repo) otherwise gets every symbol indexed several times
        # over, which manufactures clone groups and makes every name ambiguous.
        if directory in nested_cache:
            return nested_cache[directory]
        result = directory != root and (
            (directory / ".git").exists() or in_nested_checkout(directory.parent)
        )
        nested_cache[directory] = result
        return result

    found: list[Path] = []
    for p in sorted(root.glob(pattern)):
        if not p.is_file():
            continue
        # Match excludes against the path *below* the repo root. Matching the
        # absolute path would exclude an entire checkout whenever some ancestor
        # outside it happens to share a name -- a worker worktree living under
        # `.claude/worktrees/` would index nothing at all.
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(ex in rel_parts for ex in excludes):
            continue
        if in_nested_checkout(p.parent):
            continue
        found.append(p)
    return found


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _annotation_type_name(annotation: ast.expr | None) -> str | None:
    # `ledger: Ledger | None = None` and `ledger: Optional[Ledger]` both declare a
    # `Ledger`. Anything that is not one nameable class after the None is dropped
    # -- `Callable[[Path, list[str]], None]`, a union of two real classes -- has
    # no single answer, so it gets none.
    if annotation is None:
        return None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        sides = [
            _annotation_type_name(side)
            for side in (annotation.left, annotation.right)
            if not (isinstance(side, ast.Constant) and side.value is None)
        ]
        named = [s for s in sides if s]
        return named[0] if len(named) == 1 else None
    if isinstance(annotation, ast.Subscript):
        base = annotation.value
        if isinstance(base, ast.Name) and base.id == "Optional":
            return _annotation_type_name(annotation.slice)
        return None
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        # A forward reference, `ledger: "Ledger"`.
        return annotation.value or None
    return None


def _attribute_types(cls: ast.ClassDef) -> dict[str, str]:
    # `self._ledger.record(...)` is an attribute on an *instance attribute*, which
    # no amount of `self.X()` resolution can reach -- and it is how every one of
    # this SDK's seams is actually called. The declared type is the best static
    # answer available, so read it off `__init__`: either the annotation on the
    # attribute itself, or the annotation of the parameter it is assigned from.
    types: dict[str, str] = {}
    init = next(
        (
            item
            for item in cls.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        ),
        None,
    )
    if init is None:
        return types

    args = init.args
    param_types = {
        arg.arg: name
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if (name := _annotation_type_name(arg.annotation))
    }

    def target_attr(node: ast.expr) -> str | None:
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            return node.attr
        return None

    for stmt in ast.walk(init):
        if isinstance(stmt, ast.AnnAssign):
            attr = target_attr(stmt.target)
            declared = _annotation_type_name(stmt.annotation)
            if attr and declared:
                types[attr] = declared
        elif isinstance(stmt, ast.Assign):
            value = stmt.value
            # `self.github = github or GitHub(...)` still declares its type
            # through the parameter it falls back from.
            if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                value = value.values[0]
            if not isinstance(value, ast.Name):
                continue
            declared = param_types.get(value.id)
            if not declared:
                continue
            for tgt in stmt.targets:
                attr = target_attr(tgt)
                if attr:
                    types[attr] = declared
    return types


def _locally_bound_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    # A parameter or local binding shadows the module scope, so `handler()` in
    # `def dispatch(handler)` is not a call to a module-level `handler`. This
    # over-approximates by walking nested scopes too, which only ever costs us a
    # resolution -- the name falls back to the ambiguity-guarded `symbol:NAME`.
    bound: set[str] = set()
    args = fn.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        bound.add(arg.arg)
    if args.vararg:
        bound.add(args.vararg.arg)
    if args.kwarg:
        bound.add(args.kwarg.arg)
    for child in ast.walk(fn):
        if child is fn:
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            bound.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(child.name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            bound.add(child.name)
    return bound


def _import_edges(
    stmt: ast.Import | ast.ImportFrom, mod_id: str, deferred: bool
) -> tuple[dict[str, str], list[Edge]]:
    # `deferred` marks an import inside a function body. Those still tell us how
    # to resolve calls, but they do not create an import-time module dependency
    # -- they are usually written precisely to break one -- so cycle detection
    # skips them.
    aliases: dict[str, str] = {}
    edges: list[Edge] = []
    meta_extra = {"deferred": True} if deferred else {}

    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            norm_alias = (
                alias.name.removeprefix("src.") if alias.name.startswith("src.") else alias.name
            )
            aliases[alias.asname or alias.name] = norm_alias
            edges.append(
                Edge(
                    source_id=mod_id,
                    target_id=f"module:{norm_alias}",
                    kind="imports",
                    metadata={"alias": alias.asname, **meta_extra},
                )
            )
    else:
        src_mod = stmt.module or ""
        if src_mod.startswith("src."):
            src_mod = src_mod.removeprefix("src.")
        elif src_mod == "src":
            src_mod = ""
        for alias in stmt.names:
            fqn = f"{src_mod}.{alias.name}" if src_mod else alias.name
            aliases[alias.asname or alias.name] = fqn
            edges.append(
                Edge(
                    source_id=mod_id,
                    target_id=f"symbol:{fqn}" if alias.name != "*" else f"module:{src_mod}",
                    kind="imports",
                    metadata={"name": alias.name, "alias": alias.asname, **meta_extra},
                )
            )
    return aliases, edges


class PythonAstExtractor:
    """Deterministic extractor for Python source files using standard library `ast`."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def extract_file(
        self, file_path: str | Path, content: str | None = None
    ) -> tuple[list[Node], list[Edge]]:
        path_obj = Path(file_path)
        rel_path = (
            str(path_obj.relative_to(self.repo_root)) if path_obj.is_absolute() else str(path_obj)
        )

        if content is None:
            full_path = self.repo_root / rel_path
            if not full_path.exists():
                return [], []
            content = full_path.read_text(encoding="utf-8", errors="replace")

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            return [], []

        nodes: list[Node] = []
        edges: list[Edge] = []
        lines = content.splitlines()

        # Derive module id (normalizing src/ prefix if present)
        mod_path = rel_path.removeprefix("src/") if rel_path.startswith("src/") else rel_path
        mod_name = mod_path.replace("/", ".").removesuffix(".py")
        if mod_name.endswith(".__init__"):
            mod_name = mod_name.removesuffix(".__init__")
        mod_id = f"module:{mod_name}"

        mod_doc = ast.get_docstring(tree) or ""
        nodes.append(
            Node(
                id=mod_id,
                kind="module",
                name=mod_name,
                path=rel_path,
                start_line=1,
                end_line=len(lines),
                metadata={"docstring": mod_doc},
                content_hash=content_hash,
            )
        )

        import_aliases: dict[str, str] = {}  # local_alias -> target_fqn

        module_def_spans: dict[str, tuple[int, int]] = {
            stmt.name: (stmt.lineno, stmt.end_lineno or stmt.lineno)
            for stmt in tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        module_defs: set[str] = set(module_def_spans)

        # Only calls get an edge, so a symbol used as a value -- a default
        # argument (`poster: Poster = _urllib_post`), a decorator, a
        # module-level instantiation -- looked like it had no incoming edge at
        # all, and `find_unreferenced_symbols` reported live code as dead.
        # A mention inside the definition's own span is not a use of it, or
        # every recursive function would vouch for itself.
        for child in ast.walk(tree):
            if not (isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)):
                continue
            span = module_def_spans.get(child.id)
            if span is None or span[0] <= child.lineno <= span[1]:
                continue
            edges.append(
                Edge(
                    source_id=mod_id,
                    target_id=f"symbol:{mod_name}.{child.id}",
                    kind="references",
                )
            )

        # Import edges are keyed (source, target, kind), so a later deferred edge
        # would REPLACE the module-level one and mark a real import-time
        # dependency as deferred -- hiding the cycle it actually forms.
        module_import_targets: set[str] = set()

        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                aliases, import_edges = _import_edges(stmt, mod_id, deferred=False)
                import_aliases.update(aliases)
                edges.extend(import_edges)
                module_import_targets.update(e.target_id for e in import_edges)

        # Visitor for classes and functions
        class CodeVisitor(ast.NodeVisitor):
            def __init__(
                self,
                parent_id: str,
                scope_prefix: str,
                lines: list[str],
                class_methods: frozenset[str] = frozenset(),
                attr_types: dict[str, str] | None = None,
            ) -> None:
                self.parent_id = parent_id
                self.scope_prefix = scope_prefix
                self.lines = lines
                # Method names of the class being visited, so `self.X()` can be
                # resolved against it. Empty outside a class body.
                self.class_methods = class_methods
                # Declared type per instance attribute, so `self._ledger.record()`
                # can be resolved against `Ledger`. Empty outside a class body.
                self.attr_types = attr_types or {}

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                class_fqn = f"{self.scope_prefix}.{node.name}"
                class_id = f"symbol:{class_fqn}"
                class_doc = ast.get_docstring(node) or ""

                bases = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        bases.append(ast.unparse(b))

                nodes.append(
                    Node(
                        id=class_id,
                        kind="class",
                        name=node.name,
                        path=rel_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno,
                        metadata={"docstring": class_doc, "bases": bases},
                    )
                )
                edges.append(Edge(source_id=self.parent_id, target_id=class_id, kind="contains"))

                for b in bases:
                    base_target = (
                        f"symbol:{import_aliases.get(b, b)}"
                        if b in import_aliases
                        else f"symbol:{b}"
                    )
                    edges.append(
                        Edge(
                            source_id=class_id,
                            target_id=base_target,
                            kind="inherits",
                        )
                    )

                own_methods = frozenset(
                    item.name
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                inner_visitor = CodeVisitor(
                    class_id, class_fqn, self.lines, own_methods, _attribute_types(node)
                )
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        inner_visitor.visit_FunctionDef(item, is_method=True)
                    elif isinstance(item, ast.ClassDef):
                        inner_visitor.visit_ClassDef(item)

            def visit_FunctionDef(
                self,
                node: ast.FunctionDef | ast.AsyncFunctionDef,
                is_method: bool = False,
            ) -> None:
                fn_fqn = f"{self.scope_prefix}.{node.name}"
                fn_id = f"symbol:{fn_fqn}"
                fn_doc = ast.get_docstring(node) or ""
                kind = "method" if is_method else "function"

                # Extract parameters and return annotation
                params = [a.arg for a in node.args.args]
                ret_type = ast.unparse(node.returns) if node.returns else None

                fn_lines = self.lines[(node.lineno - 1) : node.end_lineno]
                fn_src = "\n".join(fn_lines)
                fn_content_hash = hashlib.sha256(fn_src.strip().encode("utf-8")).hexdigest()[:16]
                shape_hash = _compute_ast_shape_hash(node)

                nodes.append(
                    Node(
                        id=fn_id,
                        kind=kind,
                        name=node.name,
                        path=rel_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno,
                        metadata={
                            "docstring": fn_doc,
                            "params": params,
                            "returns": ret_type,
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                            "shape_hash": shape_hash,
                        },
                        content_hash=fn_content_hash,
                    )
                )
                edges.append(Edge(source_id=self.parent_id, target_id=fn_id, kind="contains"))

                # Imports written inside the body (this codebase defers them to
                # keep the package import-light) bind names for this function
                # only, shadowing the module scope.
                scope_aliases = dict(import_aliases)
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        local_aliases, local_edges = _import_edges(child, mod_id, deferred=True)
                        scope_aliases.update(local_aliases)
                        edges.extend(
                            e for e in local_edges if e.target_id not in module_import_targets
                        )

                if ret_type:
                    type_target = (
                        f"symbol:{scope_aliases.get(ret_type, ret_type)}"
                        if ret_type in scope_aliases
                        else f"symbol:{ret_type}"
                    )
                    edges.append(
                        Edge(
                            source_id=fn_id,
                            target_id=type_target,
                            kind="references_type",
                        )
                    )

                # Names rebound in this function do not reach the module scope.
                shadowed = _locally_bound_names(node)

                # Find calls inside the function body
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        resolved_target = None
                        if isinstance(child.func, ast.Name):
                            name = child.func.id
                            if name in shadowed:
                                resolved_target = f"symbol:{name}"
                            elif name in scope_aliases:
                                resolved_target = f"symbol:{scope_aliases[name]}"
                            elif name in module_defs:
                                # Python resolves a bare name to this module's
                                # own definition before anything global.
                                resolved_target = f"symbol:{mod_name}.{name}"
                            else:
                                resolved_target = f"symbol:{name}"
                        elif isinstance(child.func, ast.Attribute):
                            attr = child.func.attr
                            # `mod.fn()` where `mod` is an imported module is
                            # fully resolvable; `self.fn()` and other receivers
                            # are not, and stay a bare name for the
                            # unambiguous-name fallback to judge.
                            base = child.func.value
                            if (
                                isinstance(base, ast.Name)
                                and base.id in ("self", "cls")
                                and attr in self.class_methods
                            ):
                                # The enclosing class is known statically here,
                                # so this is exact -- no ambiguity guard needed.
                                # Without it every `self.run()` degrades to the
                                # bare name `run`, which 50 classes share, and
                                # the uniqueness rule then drops the edge
                                # entirely: the method reads as uncalled and
                                # untested.
                                resolved_target = f"symbol:{self.scope_prefix}.{attr}"
                            elif (
                                isinstance(base, ast.Name)
                                and base.id in scope_aliases
                                and base.id not in shadowed
                            ):
                                resolved_target = f"symbol:{scope_aliases[base.id]}.{attr}"
                            elif (
                                isinstance(base, ast.Attribute)
                                and isinstance(base.value, ast.Name)
                                and base.value.id in ("self", "cls")
                                and base.attr in self.attr_types
                            ):
                                # `self._ledger.record(...)`. The declared type of
                                # the attribute is the best static answer there is,
                                # and it is the one the caller programs against.
                                declared = self.attr_types[base.attr]
                                owner = scope_aliases.get(declared)
                                if owner is None:
                                    owner = (
                                        f"{mod_name}.{declared}"
                                        if declared in module_defs
                                        else declared
                                    )
                                resolved_target = f"symbol:{owner}.{attr}"
                            else:
                                resolved_target = f"symbol:{attr}"

                        if resolved_target:
                            edges.append(
                                Edge(
                                    source_id=fn_id,
                                    target_id=resolved_target,
                                    kind="calls",
                                )
                            )

        top_visitor = CodeVisitor(mod_id, mod_name, lines)
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                top_visitor.visit_ClassDef(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top_visitor.visit_FunctionDef(stmt)

        return nodes, edges

    def index_repo(
        self,
        graph: CodebaseGraph,
        pattern: str = "**/*.py",
        excludes: Sequence[str] = DEFAULT_EXCLUDES,
    ) -> None:
        """Deterministically index all matching Python files in the repository."""
        for p in _iter_repo_files(self.repo_root, pattern, excludes):
            nodes, edges = self.extract_file(p)
            graph.add_nodes(nodes)
            graph.add_edges(edges)


class MarkdownExtractor:
    """Deterministic extractor for Markdown documentation and ADRs."""

    _HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    _SYMBOL_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_\.]*)`")
    _LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def extract_file(
        self, file_path: str | Path, content: str | None = None
    ) -> tuple[list[Node], list[Edge]]:
        path_obj = Path(file_path)
        rel_path = (
            str(path_obj.relative_to(self.repo_root)) if path_obj.is_absolute() else str(path_obj)
        )

        if content is None:
            full_path = self.repo_root / rel_path
            if not full_path.exists():
                return [], []
            content = full_path.read_text(encoding="utf-8", errors="replace")

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lines = content.splitlines()

        nodes: list[Node] = []
        edges: list[Edge] = []

        page_id = f"doc:{rel_path}"
        is_adr = "adr" in rel_path.lower() or "adrs" in rel_path.lower()
        page_kind = "adr" if is_adr else "doc_page"

        nodes.append(
            Node(
                id=page_id,
                kind=page_kind,
                name=path_obj.stem,
                path=rel_path,
                start_line=1,
                end_line=len(lines),
                content_hash=content_hash,
            )
        )

        # Parse sections by headers
        current_section_id = page_id
        for i, line in enumerate(lines, start=1):
            h_match = self._HEADER_RE.match(line)
            if h_match:
                level = len(h_match.group(1))
                title = h_match.group(2).strip()
                slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.lower()).strip("-")
                section_id = f"{page_id}#{slug}"
                sec_kind = (
                    "invariant"
                    if "invariant" in title.lower() or "rule" in title.lower()
                    else "doc_section"
                )

                nodes.append(
                    Node(
                        id=section_id,
                        kind=sec_kind,
                        name=title,
                        path=rel_path,
                        start_line=i,
                        end_line=i,
                        metadata={"level": level},
                    )
                )
                edges.append(
                    Edge(
                        source_id=page_id,
                        target_id=section_id,
                        kind="contains",
                    )
                )
                current_section_id = section_id

            # Extract markdown hyperlinks
            for l_match in self._LINK_RE.finditer(line):
                target_url = l_match.group(2)
                if not target_url.startswith(("http://", "https://", "mailto:")):
                    target_doc_id = f"doc:{target_url}"
                    edges.append(
                        Edge(
                            source_id=current_section_id,
                            target_id=target_doc_id,
                            kind="links_to",
                            metadata={"text": l_match.group(1)},
                        )
                    )

            # Ground backticked symbols to code symbols
            for s_match in self._SYMBOL_RE.finditer(line):
                symbol_name = s_match.group(1)
                symbol_target_id = f"symbol:{symbol_name}"
                edges.append(
                    Edge(
                        source_id=current_section_id,
                        target_id=symbol_target_id,
                        kind="documents",
                        metadata={"line": i},
                    )
                )

        return nodes, edges

    def index_docs(
        self,
        graph: CodebaseGraph,
        pattern: str = "**/*.md",
        excludes: Sequence[str] = DEFAULT_EXCLUDES,
    ) -> None:
        """Deterministically index markdown files and cross-link with code symbols."""
        for p in _iter_repo_files(self.repo_root, pattern, excludes):
            nodes, edges = self.extract_file(p)
            graph.add_nodes(nodes)
            graph.add_edges(edges)


# An ACP is pasted verbatim into an ephemeral worker's prompt, so every section
# needs a ceiling: a hub symbol with 200 callers would otherwise crowd out the
# issue itself. Truncation is always reported so the agent knows the list it is
# reading is partial rather than complete.
MAX_ACP_CALLERS = 25
MAX_ACP_CALLEES = 15
MAX_ACP_TYPES = 15
MAX_ACP_TESTS = 25
MAX_ACP_FOCUS_LINES = 400


def render_context_pack(graph: CodebaseGraph, seed_id: str, repo_root: str | Path) -> str:
    """Generate an Agent Context Pack (ACP) constraining ephemeral agent blast radius."""
    root = Path(repo_root).resolve()
    blast = graph.blast_radius(seed_id)
    if not blast.focus_node:
        return f"# Agent Context Pack: {seed_id}\n\nSeed node not found in graph.\n"

    focus = blast.focus_node
    target_path = root / focus.path

    # Read focus implementation body
    focus_code = ""
    if target_path.exists():
        lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = (focus.start_line or 1) - 1
        end = focus.end_line or len(lines)
        body = lines[start:end]
        if len(body) > MAX_ACP_FOCUS_LINES:
            omitted = len(body) - MAX_ACP_FOCUS_LINES
            body = body[:MAX_ACP_FOCUS_LINES]
            body.append(f"# ... {omitted} more line(s) omitted; read {focus.path} for the rest.")
        focus_code = "\n".join(body)

    lines_out: list[str] = [
        f"# Agent Context Pack (ACP): {focus.name}",
        f"**Target Symbol**: `{focus.id}`",
        f"**Target File**: `{focus.path}` (L{focus.start_line or 1}-L{focus.end_line or 'EOF'})",
        "",
        "## 1. Focus Zone (Allowed Mutation Target)",
        "```python",
        focus_code,
        "```",
        "",
        "## 2. Interface Zone (Read-Only Skeletons of Downstream & Types)",
    ]

    if blast.downstream_callees:
        lines_out.append("### Downstream Callees")
        for c in blast.downstream_callees[:MAX_ACP_CALLEES]:
            params = ", ".join(c.metadata.get("params", []))
            ret = c.metadata.get("returns")
            ret_sig = f" -> {ret}" if ret else ""
            doc = c.metadata.get("docstring", "")
            doc_line = f'    """{doc}"""\n' if doc else ""
            lines_out.append(f"```python\ndef {c.name}({params}){ret_sig}:\n{doc_line}    ...\n```")
        if len(blast.downstream_callees) > MAX_ACP_CALLEES:
            extra = len(blast.downstream_callees) - MAX_ACP_CALLEES
            lines_out.append(f"_...and {extra} more callee(s), omitted._")
    else:
        lines_out.append("_No direct downstream callees._")

    if blast.types:
        lines_out.append("")
        lines_out.append("### Referenced Types")
        for t in blast.types[:MAX_ACP_TYPES]:
            lines_out.append(f"- `{t.name}` ({t.kind}, `{t.path}`:L{t.start_line or 1})")

    # Callers are the whole point of a blast radius: they are what a signature
    # change breaks. blast_radius() has always computed them; the pack used to
    # drop them on the floor, so agents saw only what the focus calls, never
    # what calls the focus.
    lines_out.append("")
    lines_out.append("## 3. Impact Zone (Callers -- a signature change breaks these)")
    if blast.upstream_callers:
        test_ids = {t.id for t in blast.tests}
        non_test = [c for c in blast.upstream_callers if c.id not in test_ids]
        shown = non_test[:MAX_ACP_CALLERS]
        for c in shown:
            lines_out.append(f"- `{c.path}`:L{c.start_line or 1} — `{c.name}`")
        if len(non_test) > len(shown):
            lines_out.append(f"_...and {len(non_test) - len(shown)} more caller(s), omitted._")
        if not non_test:
            lines_out.append("_All callers are tests; see section 5._")
    else:
        lines_out.append("_No callers found. Treat the signature as still load-bearing:_")
        lines_out.append(
            "_unresolved dynamic calls and cross-repo importers are invisible to this graph._"
        )

    lines_out.append("")
    lines_out.append("## 4. Governing Invariants & Documentation")
    if blast.invariants or blast.docs:
        for inv in blast.invariants + blast.docs:
            lines_out.append(f"- **{inv.name}** (`{inv.path}`:L{inv.start_line or 1})")
    else:
        lines_out.append("_No explicit ADRs or invariants linked._")

    lines_out.append("")
    lines_out.append("## 5. Discovered Test Verification Targets")
    if blast.tests:
        for t in blast.tests[:MAX_ACP_TESTS]:
            lines_out.append(f"- `{t.path}::{t.name}`")
        if len(blast.tests) > MAX_ACP_TESTS:
            lines_out.append(f"_...and {len(blast.tests) - MAX_ACP_TESTS} more test(s), omitted._")
    else:
        lines_out.append("_No direct unit test targets detected in blast radius._")

    lines_out.append("")
    lines_out.append("## 6. Scope Boundary Constraint")
    lines_out.append(
        f"- Mutation must be strictly confined to `{focus.path}` within symbol `{focus.name}`."
    )
    lines_out.append("- Do not modify interface signatures without human approval.")
    lines_out.append("")

    return "\n".join(lines_out)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for mythings.graph: index, analyze, and render ACP."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m mythings.graph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    idx_p = sub.add_parser("index", help="Index a repository into SQLite graph")
    idx_p.add_argument("repo", type=Path, help="Repository root path")
    idx_p.add_argument("--db", type=Path, default=None, help="Output SQLite database path")

    anl_p = sub.add_parser(
        "analyze", help="Analyze codebase graph for clones, test gaps, and issues"
    )
    anl_p.add_argument("repo", type=Path, help="Repository root path or SQLite database path")
    anl_p.add_argument(
        "--clones", action="store_true", help="Detect structural and exact code clones"
    )
    anl_p.add_argument(
        "--test-gaps", action="store_true", help="Detect production symbols lacking tests"
    )
    anl_p.add_argument(
        "--untested-invariants", action="store_true", help="Detect untested ADRs/invariants"
    )
    anl_p.add_argument("--cycles", action="store_true", help="Detect circular module imports")
    anl_p.add_argument("--unreferenced", action="store_true", help="Detect dead internal symbols")
    anl_p.add_argument("--json", action="store_true", help="Output findings as JSON")

    acp_p = sub.add_parser("acp", help="Render Agent Context Pack for a seed symbol")
    acp_p.add_argument("repo", type=Path, help="Repository root path")
    acp_p.add_argument("symbol", help="Target symbol ID or name")
    acp_p.add_argument("--db", type=Path, default=None, help="SQLite database path")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd == "index":
        repo_path = args.repo.resolve()
        db_path = args.db or (repo_path / ".mythings" / "graph.sqlite")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        graph = CodebaseGraph(db_path)
        PythonAstExtractor(repo_root=repo_path).index_repo(graph)
        MarkdownExtractor(repo_root=repo_path).index_docs(graph)
        graph.close()
        print(f"Indexed {repo_path} -> {db_path}")
        return 0

    if args.cmd == "acp":
        repo_path = args.repo.resolve()
        db_path = args.db or (repo_path / ".mythings" / "graph.sqlite")
        cached = CodebaseGraph.open_cached(db_path)
        if cached is None:
            graph = CodebaseGraph.in_memory()
            PythonAstExtractor(repo_root=repo_path).index_repo(graph)
            MarkdownExtractor(repo_root=repo_path).index_docs(graph)
        else:
            graph = cached
        seed_id = args.symbol if args.symbol.startswith("symbol:") else f"symbol:{args.symbol}"
        if not graph.get_node(seed_id):
            matches = graph.find_symbols(args.symbol)
            if matches:
                seed_id = matches[0].id
        pack = render_context_pack(graph, seed_id, repo_root=repo_path)
        print(pack)
        graph.close()
        return 0

    if args.cmd == "analyze":
        repo_path = args.repo.resolve()
        if repo_path.is_file():
            graph = CodebaseGraph(repo_path)
        else:
            db_path = repo_path / ".mythings" / "graph.sqlite"
            cached = CodebaseGraph.open_cached(db_path)
            if cached is not None:
                graph = cached
            else:
                graph = CodebaseGraph.in_memory()
                PythonAstExtractor(repo_root=repo_path).index_repo(graph)
                MarkdownExtractor(repo_root=repo_path).index_docs(graph)

        run_all = not (
            args.clones
            or args.test_gaps
            or args.untested_invariants
            or args.cycles
            or args.unreferenced
        )

        data: dict[str, Any] = {}
        if run_all or args.clones:
            clones = graph.find_structural_clones()
            data["clones"] = [
                {
                    "hash": c.hash_value,
                    "type": c.clone_type,
                    "nodes": [{"id": n.id, "path": n.path, "name": n.name} for n in c.nodes],
                }
                for c in clones
            ]

        if run_all or args.test_gaps:
            gaps = graph.find_test_gaps()
            data["test_gaps"] = [
                {
                    "symbol": g.symbol.id,
                    "path": g.symbol.path,
                    "name": g.symbol.name,
                    "caller_count": g.caller_count,
                    "callers": [c.id for c in g.callers],
                }
                for g in gaps
            ]

        if run_all or args.untested_invariants:
            untested = graph.find_untested_invariants()
            data["untested_invariants"] = [
                {
                    "invariant": u.invariant.id,
                    "path": u.invariant.path,
                    "name": u.invariant.name,
                    "governed_symbols": [s.id for s in u.governed_symbols],
                }
                for u in untested
            ]

        if run_all or args.cycles:
            cycles = graph.find_circular_imports()
            data["circular_imports"] = cycles

        if run_all or args.unreferenced:
            dead = graph.find_unreferenced_symbols()
            data["unreferenced_symbols"] = [
                {"id": n.id, "path": n.path, "name": n.name} for n in dead
            ]

        graph.close()

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            if "clones" in data and data["clones"]:
                print(f"=== Structural Clones ({len(data['clones'])}) ===")
                for c in data["clones"]:
                    names = ", ".join(f"{n['path']}:{n['name']}" for n in c["nodes"])
                    print(f"  [{c['type']}] {c['hash']}: {names}")
            if "test_gaps" in data and data["test_gaps"]:
                print(f"\n=== Test Gaps ({len(data['test_gaps'])}) ===")
                for g in data["test_gaps"]:
                    print(f"  {g['symbol']} ({g['path']}) has {g['caller_count']} callers, 0 tests")
            if "untested_invariants" in data and data["untested_invariants"]:
                print(f"\n=== Untested Invariants ({len(data['untested_invariants'])}) ===")
                for u in data["untested_invariants"]:
                    sym_count = len(u["governed_symbols"])
                    print(f"  {u['invariant']} ({u['path']}) -> {sym_count} untested symbols")
            if "circular_imports" in data and data["circular_imports"]:
                print(f"\n=== Circular Imports ({len(data['circular_imports'])}) ===")
                for cyc in data["circular_imports"]:
                    print(f"  {' -> '.join(cyc)}")
            if "unreferenced_symbols" in data and data["unreferenced_symbols"]:
                print(f"\n=== Unreferenced Symbols ({len(data['unreferenced_symbols'])}) ===")
                for d in data["unreferenced_symbols"]:
                    print(f"  {d['id']} ({d['path']})")

        return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
