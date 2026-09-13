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


def test_structural_clones_detection():
    sample1 = """def add_numbers(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    result = a + b
    return result

def identical_copy(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    result = a + b
    return result
"""
    sample2 = """def sum_values(x: int, y: int) -> int:
    # Notice different variable names and docstring, but identical AST shape
    total = x + y
    return total

def different_op(x: int, y: int) -> int:
    return x * y
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "mod1.py").write_text(sample1)
        (root / "mod2.py").write_text(sample2)

        graph = CodebaseGraph.in_memory()
        extractor = PythonAstExtractor(repo_root=root)
        extractor.index_repo(graph)

        clones = graph.find_structural_clones(min_lines=3)
        assert len(clones) >= 1

        types = {c.clone_type for c in clones}
        # Both exact clone group (add_numbers & identical_copy) and
        # structural clone group (with sum_values)
        assert "exact" in types or "structural" in types
        all_clone_names = {n.name for c in clones for n in c.nodes}
        assert "add_numbers" in all_clone_names
        assert "identical_copy" in all_clone_names
        assert "sum_values" in all_clone_names
        assert "different_op" not in all_clone_names


def test_test_gaps_and_untested_invariants():
    service_code = """def caller_service(x: int) -> int:
    return untest_helper(x) + tested_helper(x)

def untest_helper(x: int) -> int:
    return x * 10

def tested_helper(x: int) -> int:
    return x + 1
"""
    test_code = """from service import tested_helper

def test_tested_helper():
    assert tested_helper(5) == 6
"""
    doc_code = """# Architectural Decision Record

## Invariant: Untested Contract
Governs `untest_helper`. Must remain scaled by 10.
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "src").mkdir()
        (root / "src" / "service.py").write_text(service_code)
        (root / "tests").mkdir()
        (root / "tests" / "test_service.py").write_text(test_code)
        (root / "docs").mkdir()
        (root / "docs" / "adr.md").write_text(doc_code)

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)
        MarkdownExtractor(repo_root=root).index_docs(graph)

        # untest_helper is called by caller_service, but has 0 test callers!
        gaps = graph.find_test_gaps(min_callers=1)
        gap_names = {g.symbol.name for g in gaps}
        assert "untest_helper" in gap_names
        assert "tested_helper" not in gap_names

        # Invariant governs untest_helper which has no tests
        untested_invs = graph.find_untested_invariants()
        assert len(untested_invs) == 1
        assert "untested-contract" in untested_invs[0].invariant.id


def test_circular_imports_and_unreferenced_symbols():
    code_a = "from mod_b import b_fn\ndef a_fn(): return b_fn()\n"
    code_b = "from mod_a import a_fn\ndef b_fn(): return 1\ndef _dead_internal(): return 99\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "mod_a.py").write_text(code_a)
        (root / "mod_b.py").write_text(code_b)

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        # Circular import mod_a <-> mod_b
        cycles = graph.find_circular_imports()
        assert len(cycles) == 1
        assert "module:mod_a" in cycles[0]
        assert "module:mod_b" in cycles[0]

        # Dead internal symbol _dead_internal has zero callers
        unreferenced = graph.find_unreferenced_symbols()
        assert any(u.name == "_dead_internal" for u in unreferenced)


def test_cli_entrypoint(capsys):
    from mythings.graph import main

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calc.py").write_text("def calc(a, b): return a + b\n")

        # CLI index
        ret = main(["index", str(root)])
        assert ret == 0
        db_path = root / ".mythings" / "graph.sqlite"
        assert db_path.exists()

        # CLI analyze --json
        ret_anl = main(["analyze", str(root), "--json"])
        assert ret_anl == 0
        captured = capsys.readouterr()
        assert "clones" in captured.out
        assert "test_gaps" in captured.out
