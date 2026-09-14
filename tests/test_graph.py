import tempfile
from pathlib import Path

from mythings.graph import (
    MAX_ACP_CALLERS,
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


def test_ambiguous_name_does_not_leak_into_blast_radius():
    # Two unrelated modules each define `main`. A bare `main()` call in one
    # module's tests must not appear in the other's blast radius.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "alpha.py").write_text(
            "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
            encoding="utf-8",
        )
        (root / "beta.py").write_text(
            "def main():\n    return 2\n",
            encoding="utf-8",
        )
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_beta.py").write_text(
            "def test_beta_main():\n    main()\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        blast = graph.blast_radius("symbol:alpha.helper")
        caller_names = {c.name for c in blast.upstream_callers}
        assert "main" in caller_names  # alpha.main really does call helper
        assert "test_beta_main" not in caller_names
        assert not blast.tests

        # The seed's own name gets the same guard as every recursive hop:
        # seeding the ambiguous `alpha.main` must not claim beta's test.
        ambiguous = graph.blast_radius("symbol:alpha.main")
        assert "test_beta_main" not in {c.name for c in ambiguous.upstream_callers}
        assert not ambiguous.tests


def test_function_local_import_resolves_calls():
    # This codebase defers imports into function bodies; calls resolved through
    # them must still produce edges.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "engine.py").write_text(
            "def launch():\n    return 1\n",
            encoding="utf-8",
        )
        (root / "caller.py").write_text(
            "def go():\n    from engine import launch\n    return launch()\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        blast = graph.blast_radius("symbol:engine.launch")
        assert any(c.name == "go" for c in blast.upstream_callers)


def test_module_attribute_call_resolves_to_definition():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "engine.py").write_text("def launch():\n    return 1\n", encoding="utf-8")
        (root / "caller.py").write_text(
            "import engine\n\ndef go():\n    return engine.launch()\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        blast = graph.blast_radius("symbol:engine.launch")
        assert any(c.name == "go" for c in blast.upstream_callers)


def test_deferred_import_is_not_a_circular_import():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "a.py").write_text(
            "import b\n\ndef use():\n    return b.thing()\n",
            encoding="utf-8",
        )
        # b imports a only inside the function -- the standard cycle workaround.
        (root / "b.py").write_text(
            "def thing():\n    import a\n    return a\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)
        assert graph.find_circular_imports() == []

        # A genuine import-time cycle is still reported.
        (root / "b.py").write_text("import a\n\ndef thing():\n    return a\n", encoding="utf-8")
        graph2 = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph2)
        assert graph2.find_circular_imports()

        # Both forms at once: edges are keyed (source, target, kind), so the
        # deferred re-import must not overwrite the module-level edge and
        # launder a real import-time cycle into a deferred one.
        (root / "b.py").write_text(
            "import a\n\ndef thing():\n    import a\n    return a\n",
            encoding="utf-8",
        )
        graph3 = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph3)
        assert graph3.find_circular_imports()


def test_local_binding_shadows_module_level_definition():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # `handler` is a parameter here, so `handler()` is not a call to the
        # module-level `handler` that happens to share the name. The extractor
        # must leave it unresolved rather than emit an exact-id edge, which
        # would bypass every ambiguity guard downstream.
        src = "def handler():\n    return 1\n\ndef dispatch(handler):\n    return handler()\n"
        (root / "m.py").write_text(src, encoding="utf-8")

        _, edges = PythonAstExtractor(repo_root=root).extract_file("m.py", content=src)
        call_targets = {e.target_id for e in edges if e.kind == "calls"}
        assert "symbol:handler" in call_targets
        assert "symbol:m.handler" not in call_targets

        # With a second `handler` in the repo the name is ambiguous, so the
        # unresolved edge stays unresolved and the false caller never appears.
        (root / "other.py").write_text("def handler():\n    return 2\n", encoding="utf-8")
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)
        blast = graph.blast_radius("symbol:m.handler")
        assert "dispatch" not in {c.name for c in blast.upstream_callers}


def test_context_pack_reports_callers_and_truncates():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        callers = "\n".join(
            f"def caller_{i}():\n    return hub()\n" for i in range(MAX_ACP_CALLERS + 5)
        )
        (root / "hub.py").write_text(f"def hub():\n    return 0\n\n{callers}", encoding="utf-8")

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        acp = render_context_pack(graph, "symbol:hub.hub", repo_root=root)
        assert "Impact Zone (Callers" in acp
        assert "caller_0" in acp
        assert "more caller(s), omitted" in acp


def test_test_gap_not_laundered_by_same_named_function():
    # `run` exists twice; only one is tested. The untested one must still be
    # reported as a gap.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "tested_mod.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (root / "untested_mod.py").write_text(
            "def run():\n    return 2\n\ndef consumer():\n    return run()\n",
            encoding="utf-8",
        )
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_tested.py").write_text(
            "from tested_mod import run\n\ndef test_run():\n    assert run() == 1\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        gap_ids = {g.symbol.id for g in graph.find_test_gaps()}
        assert "symbol:untested_mod.run" in gap_ids


def test_nested_checkout_is_not_indexed():
    # This fleet nests a git worktree per sibling repo inside a checkout.
    # Indexing those copies duplicates every symbol, which manufactures clone
    # groups and makes every name ambiguous.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".git").mkdir()
        (root / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")

        nested = root / ".claude" / "worktrees" / "wt1"
        nested.mkdir(parents=True)
        (nested / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        (nested / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")

        # A nested checkout not under an excluded directory name is still skipped.
        vendored = root / "vendor" / "clone"
        vendored.mkdir(parents=True)
        (vendored / ".git").mkdir()
        (vendored / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        paths = {n.path for n in graph.get_nodes_by_kind("function")}
        assert paths == {"app.py"}
        assert graph.find_structural_clones(min_lines=1) == []


def test_excludes_match_below_root_not_absolute_path():
    # A worker worktree lives under `.claude/worktrees/<name>/`, so `.claude`
    # appears in its absolute path. Matching excludes against the absolute path
    # would index zero files and silently produce an empty graph.
    with tempfile.TemporaryDirectory() as tmpdir:
        outer = Path(tmpdir) / ".claude" / "worktrees" / "wt"
        outer.mkdir(parents=True)
        (outer / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=outer).index_repo(graph)

        assert graph.get_node("symbol:app.handler") is not None


def test_traversal_works_while_iterating_a_cursor():
    # `for row in conn.execute(...): graph.blast_radius(...)` is the obvious way
    # to drive this API; refreshing the resolution index must not need a commit
    # that an open read cursor on the same connection would block.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "m.py").write_text(
            "def leaf():\n    return 1\n\ndef top():\n    return leaf()\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        seen = 0
        for row in graph.conn.execute("SELECT id FROM nodes WHERE kind = 'function'"):
            graph.blast_radius(row[0])
            seen += 1
        assert seen == 2


def test_production_file_is_not_excluded_by_like_wildcard():
    # `_` is a single-character LIKE wildcard, so an unescaped '%_test.py'
    # also swallows latest.py, contest.py and pytest.py.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "latest.py").write_text(
            "def newest():\n    return 1\n",
            encoding="utf-8",
        )
        (root / "caller.py").write_text(
            "from latest import newest\n\ndef go():\n    return newest()\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        gap_paths = {g.symbol.path for g in graph.find_test_gaps()}
        assert "latest.py" in gap_paths


def test_self_method_call_resolves_against_enclosing_class():
    # `self.X()` degrades to the bare name `X` without class-scope resolution,
    # and 50 classes in this fleet define `run` -- so the uniqueness guard then
    # drops the edge and the method reads as uncalled and untested.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "engines.py").write_text(
            "class Alpha:\n"
            "    def run(self):\n"
            "        return self.helper()\n"
            "    def helper(self):\n"
            "        return 1\n"
            "\n"
            "class Beta:\n"
            "    def run(self):\n"
            "        return self.helper()\n"
            "    def helper(self):\n"
            "        return 2\n",
            encoding="utf-8",
        )

        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        blast = graph.blast_radius("symbol:engines.Alpha.helper")
        callers = {c.id for c in blast.upstream_callers}
        assert "symbol:engines.Alpha.run" in callers
        # ...and Beta's identically-named method is not laundered in.
        assert "symbol:engines.Beta.run" not in callers


def test_ordinary_methods_are_considered_for_test_gaps():
    # `name LIKE '__%__'` was meant to skip dunders, but `_` is a wildcard, so
    # it matched every method name of four or more characters -- `close`,
    # `record`, 179 of this repo's 195 methods -- and none of them was ever
    # examined for a test gap.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "store.py").write_text(
            "class Store:\n"
            "    def __init__(self):\n"
            "        self.rows = []\n"
            "    def record(self, row):\n"
            "        self.rows.append(row)\n"
            "\n"
            "def save(s):\n"
            "    return s.record(1)\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        gap_names = {g.symbol.name for g in graph.find_test_gaps()}
        assert "record" in gap_names
        # Dunders really are still excluded.
        assert "__init__" not in gap_names


def test_symbol_used_as_a_value_is_not_reported_dead():
    # Only calls produced an edge, so a helper passed as a default argument had
    # no incoming edge at all and was reported as dead code to delete.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "post.py").write_text(
            "def _urllib_post(body):\n"
            "    return body\n"
            "\n"
            "def _never_used(body):\n"
            "    return body\n"
            "\n"
            "def send(body, poster=_urllib_post):\n"
            "    return poster(body)\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        dead = {n.name for n in graph.find_unreferenced_symbols()}
        assert "_urllib_post" not in dead
        assert "_never_used" in dead


def test_public_symbols_are_not_reported_as_dead_internals():
    # `name LIKE '_%'` does not mean "starts with an underscore" -- `_` is a
    # wildcard, so this matched every symbol and reported public API as dead.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "api.py").write_text(
            "class PublicThing:\n    pass\n\ndef _hidden():\n    return 1\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        dead = {n.name for n in graph.find_unreferenced_symbols()}
        assert "PublicThing" not in dead
        assert "_hidden" in dead


def test_open_cached_rejects_a_graph_from_another_schema_version():
    # The fleet keys this cache on the repo's commit SHA alone, so a repo whose
    # HEAD has not moved keeps serving edges an older extractor wrote. The
    # traversal discards what it cannot parse and the Agent Context Pack then
    # reports no callers and no tests, which reads as a real answer.
    import sqlite3

    from mythings.graph import GRAPH_SCHEMA_VERSION

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        db = root / "graph.sqlite"

        graph = CodebaseGraph(db)
        PythonAstExtractor(repo_root=root).index_repo(graph)
        graph.close()

        fresh = CodebaseGraph.open_cached(db)
        assert fresh is not None
        assert fresh.get_node("symbol:m.f") is not None
        fresh.close()

        stale = sqlite3.connect(str(db))
        stale.execute(f"PRAGMA user_version = {GRAPH_SCHEMA_VERSION - 1}")
        stale.commit()
        stale.close()
        assert CodebaseGraph.open_cached(db) is None

        assert CodebaseGraph.open_cached(root / "absent.sqlite") is None

        garbage = root / "garbage.sqlite"
        garbage.write_bytes(b"this is not a database")
        assert CodebaseGraph.open_cached(garbage) is None


def test_call_on_an_annotated_attribute_resolves_to_the_declared_type():
    # `self._ledger.record(...)` is an attribute on an *instance attribute*, so
    # no amount of `self.X()` resolution reaches it -- and it is how every one of
    # this SDK's seams is actually called.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "ledger.py").write_text(
            "class Ledger:\n    def record(self, msg):\n        return msg\n",
            encoding="utf-8",
        )
        (root / "runner.py").write_text(
            "from ledger import Ledger\n"
            "\n"
            "class Runner:\n"
            "    def __init__(self, ledger: Ledger | None = None, note: str = ''):\n"
            "        self._ledger = ledger\n"
            "        self.note = note\n"
            "    def go(self):\n"
            "        self._ledger.record('x')\n"
            "        return self.note.strip()\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        callers = {c.id for c in graph.blast_radius("symbol:ledger.Ledger.record").upstream_callers}
        assert "symbol:runner.Runner.go" in callers

        # `note` is a `str`, whose methods own no node here. Qualifying the
        # target anyway is the point: a bare `symbol:strip` would be eligible for
        # the unambiguous-name fallback and could be laundered onto an unrelated
        # repo function that happens to be called `strip`.
        targets = {
            r[0]
            for r in graph.conn.execute(
                "SELECT target_id FROM edges WHERE source_id = 'symbol:runner.Runner.go'"
            )
        }
        assert "symbol:str.strip" in targets
        assert "symbol:strip" not in targets
        assert graph.get_node("symbol:str.strip") is None


def test_unannotated_attribute_does_not_invent_a_call_target():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "svc.py").write_text(
            "class Other:\n    def send(self):\n        return 1\n"
            "\n"
            "class Svc:\n"
            "    def __init__(self, dep):\n"
            "        self.dep = dep\n"
            "    def go(self):\n"
            "        return self.dep.send()\n",
            encoding="utf-8",
        )
        graph = CodebaseGraph.in_memory()
        PythonAstExtractor(repo_root=root).index_repo(graph)

        targets = {
            r[0]
            for r in graph.conn.execute(
                "SELECT target_id FROM edges WHERE source_id = 'symbol:svc.Svc.go'"
            )
        }
        # Nothing declares what `dep` is, so it stays unresolved rather than
        # guessing the only class that happens to define `send`.
        assert "symbol:send" in targets
        assert "symbol:svc.Other.send" not in targets
