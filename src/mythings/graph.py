"""Deterministic property graph for code, documentation, and CAD ephemeral worker context.

Provides:
- SQLite-backed relational property graph (nodes and edges) with recursive CTE traversals.
- Deterministic Python AST extractor (modules, classes, functions, calls, imports, types).
- Deterministic Markdown extractor (headings, sections, ADRs, backtick symbol links).
- Agent Context Pack (ACP) generator to constrain ephemeral agent blast radius.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


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
        focus = self.get_node(seed_id)
        short_seed = f"symbol:{focus.name}" if focus else seed_id

        # 1. Upstream callers (reverse calls transitive closure up to 3 hops)
        caller_query = """
        WITH RECURSIVE upstream(id, depth) AS (
            SELECT source_id, 1 FROM edges
            WHERE (target_id = ? OR target_id = ?) AND kind = 'calls'
            UNION
            SELECT e.source_id, u.depth + 1
            FROM edges e
            JOIN upstream u ON (
                e.target_id = u.id
                OR (e.target_id LIKE 'symbol:%'
                    AND SUBSTR(e.target_id, 8) = (SELECT name FROM nodes WHERE id = u.id))
            )
            WHERE e.kind = 'calls' AND u.depth < 3
        )
        SELECT DISTINCT n.* FROM nodes n
        JOIN upstream u ON n.id = u.id
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
            OR (e.target_id LIKE 'symbol:%' AND n.name = SUBSTR(e.target_id, 8))
        )
        WHERE e.source_id = ? AND e.kind = 'calls'
        """
        callees = [
            self._row_to_node(r) for r in self.conn.execute(callee_query, (seed_id,)).fetchall()
        ]

        # 3. Types referenced (1 hop)
        type_query = """
        SELECT DISTINCT n.* FROM nodes n
        JOIN edges e ON n.id = e.target_id
        WHERE e.source_id = ? AND e.kind = 'references_type'
        """
        types = [self._row_to_node(r) for r in self.conn.execute(type_query, (seed_id,)).fetchall()]

        # 4. Tests covering the symbol
        # Tests are callers located in paths matching test* or tests/*
        tests = [
            c
            for c in callers
            if "test" in c.path.lower() or c.name.startswith("test_") or "tests/" in c.path
        ]

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
                end_line=len(content.splitlines()),
                metadata={"docstring": mod_doc},
                content_hash=content_hash,
            )
        )

        import_aliases: dict[str, str] = {}  # local_alias -> target_fqn

        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    norm_alias = (
                        alias.name.removeprefix("src.")
                        if alias.name.startswith("src.")
                        else alias.name
                    )
                    local_name = alias.asname or alias.name
                    import_aliases[local_name] = norm_alias
                    target_id = f"module:{norm_alias}"
                    edges.append(
                        Edge(
                            source_id=mod_id,
                            target_id=target_id,
                            kind="imports",
                            metadata={"alias": alias.asname},
                        )
                    )
            elif isinstance(stmt, ast.ImportFrom):
                src_mod = stmt.module or ""
                if src_mod.startswith("src."):
                    src_mod = src_mod.removeprefix("src.")
                elif src_mod == "src":
                    src_mod = ""
                for alias in stmt.names:
                    local_name = alias.asname or alias.name
                    fqn = f"{src_mod}.{alias.name}" if src_mod else alias.name
                    import_aliases[local_name] = fqn
                    target_id = f"symbol:{fqn}" if alias.name != "*" else f"module:{src_mod}"
                    edges.append(
                        Edge(
                            source_id=mod_id,
                            target_id=target_id,
                            kind="imports",
                            metadata={"name": alias.name, "alias": alias.asname},
                        )
                    )

        # Visitor for classes and functions
        class CodeVisitor(ast.NodeVisitor):
            def __init__(self, parent_id: str, scope_prefix: str) -> None:
                self.parent_id = parent_id
                self.scope_prefix = scope_prefix

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

                inner_visitor = CodeVisitor(class_id, class_fqn)
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
                        },
                    )
                )
                edges.append(Edge(source_id=self.parent_id, target_id=fn_id, kind="contains"))

                if ret_type:
                    type_target = (
                        f"symbol:{import_aliases.get(ret_type, ret_type)}"
                        if ret_type in import_aliases
                        else f"symbol:{ret_type}"
                    )
                    edges.append(
                        Edge(
                            source_id=fn_id,
                            target_id=type_target,
                            kind="references_type",
                        )
                    )

                # Find calls inside the function body
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        callee_name = None
                        if isinstance(child.func, ast.Name):
                            callee_name = child.func.id
                        elif isinstance(child.func, ast.Attribute):
                            callee_name = child.func.attr

                        if callee_name:
                            resolved_target = (
                                f"symbol:{import_aliases[callee_name]}"
                                if callee_name in import_aliases
                                else f"symbol:{callee_name}"
                            )
                            edges.append(
                                Edge(
                                    source_id=fn_id,
                                    target_id=resolved_target,
                                    kind="calls",
                                )
                            )

        top_visitor = CodeVisitor(mod_id, mod_name)
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
        excludes: Sequence[str] = (
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            "build",
            "dist",
        ),
    ) -> None:
        """Deterministically index all matching Python files in the repository."""
        for p in self.repo_root.glob(pattern):
            if any(ex in p.parts for ex in excludes) or not p.is_file():
                continue
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
        excludes: Sequence[str] = (".venv", "venv", ".git"),
    ) -> None:
        """Deterministically index markdown files and cross-link with code symbols."""
        for p in self.repo_root.glob(pattern):
            if any(ex in p.parts for ex in excludes) or not p.is_file():
                continue
            nodes, edges = self.extract_file(p)
            graph.add_nodes(nodes)
            graph.add_edges(edges)


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
        focus_code = "\n".join(lines[start:end])

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
        for c in blast.downstream_callees:
            params = ", ".join(c.metadata.get("params", []))
            ret = c.metadata.get("returns")
            ret_sig = f" -> {ret}" if ret else ""
            doc = c.metadata.get("docstring", "")
            doc_line = f'    """{doc}"""\n' if doc else ""
            lines_out.append(f"```python\ndef {c.name}({params}){ret_sig}:\n{doc_line}    ...\n```")
    else:
        lines_out.append("_No direct downstream callees._")

    lines_out.append("")
    lines_out.append("## 3. Governing Invariants & Documentation")
    if blast.invariants or blast.docs:
        for inv in blast.invariants + blast.docs:
            lines_out.append(f"- **{inv.name}** (`{inv.path}`:L{inv.start_line or 1})")
    else:
        lines_out.append("_No explicit ADRs or invariants linked._")

    lines_out.append("")
    lines_out.append("## 4. Discovered Test Verification Targets")
    if blast.tests:
        for t in blast.tests:
            lines_out.append(f"- `{t.path}::{t.name}`")
    else:
        lines_out.append("_No direct unit test targets detected in blast radius._")

    lines_out.append("")
    lines_out.append("## 5. Scope Boundary Constraint")
    lines_out.append(
        f"- Mutation must be strictly confined to `{focus.path}` within symbol `{focus.name}`."
    )
    lines_out.append("- Do not modify interface signatures without human approval.")
    lines_out.append("")

    return "\n".join(lines_out)
