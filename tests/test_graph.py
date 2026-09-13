import tempfile
from pathlib import Path

from mythings.graph import (
    CodebaseGraph,
    Edge,
    MarkdownExtractor,
    Node,
    PythonAstExtractor,
    render_context_pack,
)


def test_codebase_graph_schema_and_crud():
    graph = CodebaseGraph.in_memory()

    n1 = Node(
        id="symbol:pkg.foo",
        kind="function",
        name="foo",
        path="src/pkg/foo.py",
        start_line=1,
        end_line=10,
        metadata={"returns": "int"},
    )
    n2 = Node(
        id="symbol:pkg.bar",
        kind="function",
        name="bar",
        path="src/pkg/bar.py",
        start_line=5,
        end_line=15,
        metadata={"returns": "None"},
    )
    graph.add_nodes([n1, n2])

    e1 = Edge(source_id=n1.id, target_id=n2.id, kind="calls")
    graph.add_edge(e1)

    assert graph.get_node(n1.id) == n1
    assert graph.get_node("nonexistent") is None
    assert graph.get_nodes_by_kind("function") == [n1, n2]
    assert graph.get_nodes_by_path("src/pkg/foo.py") == [n1]

    # Neighbors
    out_neighbors = graph.neighbors(n1.id, direction="out")
    assert out_neighbors == [n2]
    in_neighbors = graph.neighbors(n2.id, direction="in")
    assert in_neighbors == [n1]

    # Filter by kind
    assert graph.neighbors(n1.id, direction="out", edge_kinds=["calls"]) == [n2]
    assert graph.neighbors(n1.id, direction="out", edge_kinds=["imports"]) == []

    graph.close()


def test_k_hop_subgraph():
    graph = CodebaseGraph.in_memory()

    nodes = [Node(id=f"n{i}", kind="function", name=f"f{i}", path="test.py") for i in range(1, 5)]
    graph.add_nodes(nodes)

    # 1 -> 2 -> 3 -> 4
    graph.add_edges(
        [
            Edge(source_id="n1", target_id="n2", kind="calls"),
            Edge(source_id="n2", target_id="n3", kind="calls"),
            Edge(source_id="n3", target_id="n4", kind="calls"),
        ]
    )

    sub_nodes, sub_edges = graph.k_hop_subgraph(["n1"], k=1)
    assert {n.id for n in sub_nodes} == {"n1", "n2"}
    assert len(sub_edges) == 1

    sub_nodes_2, sub_edges_2 = graph.k_hop_subgraph(["n1"], k=2)
    assert {n.id for n in sub_nodes_2} == {"n1", "n2", "n3"}
    assert len(sub_edges_2) == 2


def test_python_ast_extractor():
    sample_code = '''"""Module docstring."""
from typing import Optional
from mythings.ledger import LedgerEntry

class MyWorker:
    """Worker class."""
    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, task_id: str) -> Optional[LedgerEntry]:
        """Execute a task."""
        self.helper()
        return None

    def helper(self) -> None:
        pass

def standalone() -> int:
    return 42
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_file = root / "src" / "pkg" / "worker.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text(sample_code, encoding="utf-8")

        extractor = PythonAstExtractor(repo_root=root)
        nodes, edges = extractor.extract_file(src_file)

        node_map = {n.id: n for n in nodes}
        assert "module:pkg.worker" in node_map
        assert "symbol:pkg.worker.MyWorker" in node_map
        assert "symbol:pkg.worker.MyWorker.execute" in node_map
        assert "symbol:pkg.worker.standalone" in node_map

        exec_node = node_map["symbol:pkg.worker.MyWorker.execute"]
        assert exec_node.metadata["params"] == ["self", "task_id"]
        assert "Optional[LedgerEntry]" in exec_node.metadata["returns"]

        edge_kinds = [(e.source_id, e.target_id, e.kind) for e in edges]
        # Should import LedgerEntry
        assert any(e[2] == "imports" and "LedgerEntry" in e[1] for e in edge_kinds)
        # execute calls helper
        assert any(
            e[0] == "symbol:pkg.worker.MyWorker.execute" and "helper" in e[1] and e[2] == "calls"
            for e in edge_kinds
        )


def test_markdown_extractor_and_grounding():
    sample_md = """# Architecture Overview

General system architecture.

## Invariant: Append-only Ledger

Every change to `LedgerEntry` must be append-only.
See also [docs/CONVENTIONS.md](CONVENTIONS.md).

## Calling `MyWorker.execute`

Detailed explanation of how `execute` runs.
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        doc_file = root / "docs" / "ARCHITECTURE.md"
        doc_file.parent.mkdir(parents=True)
        doc_file.write_text(sample_md, encoding="utf-8")

        extractor = MarkdownExtractor(repo_root=root)
        nodes, edges = extractor.extract_file(doc_file)

        node_map = {n.id: n for n in nodes}
        assert "doc:docs/ARCHITECTURE.md" in node_map
        assert "doc:docs/ARCHITECTURE.md#invariant-append-only-ledger" in node_map
        inv_node = node_map["doc:docs/ARCHITECTURE.md#invariant-append-only-ledger"]
        assert inv_node.kind == "invariant"

        # Grounded backtick symbol
        edge_kinds = [(e.source_id, e.target_id, e.kind) for e in edges]
        assert any(e[1] == "symbol:LedgerEntry" and e[2] == "documents" for e in edge_kinds)
        assert any(e[1] == "doc:CONVENTIONS.md" and e[2] == "links_to" for e in edge_kinds)


def test_blast_radius_and_agent_context_pack():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Code file
        code_file = root / "src" / "service.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text(
            """def target_fn(x: int) -> int:
    \"\"\"Target function to edit.\"\"\"
    return helper_callee(x)

def helper_callee(val: int) -> int:
    \"\"\"Helper callee docstring.\"\"\"
    return val * 2
""",
            encoding="utf-8",
        )

        # Test file
        test_file = root / "tests" / "test_service.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            """from src.service import target_fn

def test_target_fn():
    assert target_fn(2) == 4
""",
            encoding="utf-8",
        )

        # Doc file with invariant
        doc_file = root / "docs" / "ADR-001.md"
        doc_file.parent.mkdir(parents=True)
        doc_file.write_text(
            """# ADR 001

## Invariant: Deterministic Multiplier
Governs `target_fn`. Never change multiplication factor without review.
""",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        py_ext = PythonAstExtractor(repo_root=root)
        py_ext.index_repo(graph)

        md_ext = MarkdownExtractor(repo_root=root)
        md_ext.index_docs(graph)

        seed_id = "symbol:service.target_fn"

        # Link invariant to target_fn
        inv_id = "doc:docs/ADR-001.md#invariant-deterministic-multiplier"
        graph.add_edge(Edge(source_id=inv_id, target_id=seed_id, kind="governs"))

        blast = graph.blast_radius(seed_id)
        assert blast.focus_node is not None
        assert blast.focus_node.name == "target_fn"
        assert any(c.name == "helper_callee" for c in blast.downstream_callees)
        assert any("test_target_fn" in t.name for t in blast.tests)
        assert any(i.id == inv_id for i in blast.invariants)

        # Render ACP
        acp = render_context_pack(graph, seed_id, repo_root=root)
        assert "Agent Context Pack (ACP): target_fn" in acp
        assert "Focus Zone (Allowed Mutation Target)" in acp
        assert "def helper_callee" in acp
        assert "Invariant: Deterministic Multiplier" in acp
        assert "test_service.py::test_target_fn" in acp
        assert "Scope Boundary Constraint" in acp
