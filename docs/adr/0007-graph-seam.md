# ADR 0007 — the deterministic codebase, documentation & context graph

- **Status:** Accepted (2026-09-13)
- **Issues:** [my-things-core#165](https://github.com/MyThingsLab/my-things-core/issues/165), [my-things-core#166](https://github.com/MyThingsLab/my-things-core/issues/166), [my-things-core#167](https://github.com/MyThingsLab/my-things-core/issues/167)
- **Related:** [my-fleet#76](https://github.com/MyThingsLab/my-fleet/issues/76), [my-coder#44](https://github.com/MyThingsLab/my-coder/issues/44), [my-fleet#77](https://github.com/MyThingsLab/my-fleet/issues/77)

## Context

In Continuous Autonomous Development (CAD), ephemeral worker agents (such as dispatched `my-coder` workers) are assigned tasks across heterogeneous repositories. Prior to this seam, agents either searched the filesystem with unguided grep/find or received entire file trees. This generated two complementary failure modes:

1. **Context bloat & token dilution:** Unpruned files flooded the model prompt, leading to high API costs, attention fatigue, and degraded instruction following.
2. **Context starvation & boundary violations:** Workers could not deterministically see transitive callers, referenced types, or governing architectural invariants, leading to mutations that broke downstream contracts outside the edit site.

Traditional vector embeddings ("chunk-and-embed" RAG) fail for deterministic code workflows: they hallucinate links, lack relational rigor, and cannot compute exact transitive call graphs or blast radii.

## Decision

**Promote into core**, as `mythings.graph`. A shared, 100% deterministic, zero-dependency property graph seam combining code structure, documentation ASTs, and context slicing.

Like `mythings.testers`, it is backed by Python standard library `sqlite3` and is **inert until constructed**. It requires zero external database daemons or third-party packages.

### Relational Substrate & Graph Primitives

`CodebaseGraph` defines two indexed relational tables:

- **`nodes`**: `(id, kind, name, path, start_line, end_line, metadata_json, content_hash)`
  - Symbol IDs: `symbol:<fqn>` (e.g. `symbol:mythings.ledger.Ledger.append`).
  - Module IDs: `module:<fqn>` (e.g. `module:mythings.ledger`).
  - Document IDs: `doc:<path>` and `doc:<path>#<slug>` (e.g. `doc:docs/ARCHITECTURE.md#ledger`).
  - Invariant/ADR IDs: `doc:<path>#<invariant-slug>`.
- **`edges`**: `(source_id, target_id, kind, metadata_json)`
  - Edge kinds: `contains`, `imports`, `calls`, `references_type`, `inherits`, `implements`, `documents`, `governs`, `satisfies`, `links_to`.

### Recursive Traversal via SQLite Common Table Expressions (CTEs)

Graph queries run directly inside SQLite via recursive Common Table Expressions without pulling graph data into Python object graphs:

- **`neighbors(node_id, direction, edge_kinds)`**: 1-hop directional filtering.
- **`k_hop_subgraph(seed_ids, k)`**: Multi-hop structural subgraphs.
- **`blast_radius(seed_id)`**:
  - Upstream callers: Transitive reverse closure along `calls` edges up to 3 hops.
  - Downstream callees: 1-hop outgoing `calls` edges.
  - Types referenced: 1-hop `references_type` edges.
  - Test targets: Discovered unit tests exercising the symbol.
  - Invariants: Governing ADR and convention nodes connected via `governs`, `satisfies`, or `documents`.

### Deterministic Extractors

1. **`PythonAstExtractor`**:
   - Parses code using standard library `ast.parse`.
   - Never imports target code (guarantees safety from side effects and missing dependencies).
   - Normalizes package layout (`src/` prefix handling).
   - Captures class hierarchies, function signatures, return types, docstrings, and call invocations.
2. **`MarkdownExtractor`**:
   - Parses document structure hierarchically (document page -> sections H1-H6 -> blocks).
   - Extracts relative document links.
   - Detects ADR and invariant sections from markdown titles.
   - Deterministically grounds backticked symbols (e.g. `` `LedgerEntry.to_json` ``) to code nodes via `documents` edges.

### Ephemeral Worker Context Slicing: Agent Context Packs (ACP)

`render_context_pack(graph, seed_id, repo_root)` synthesizes an **Agent Context Pack (ACP)**:
- **Focus Zone**: Full source code of the mutation target.
- **Interface Zone**: Read-only skeletons (signatures, types, docstrings) of caller and callee neighbors.
- **Invariant Zone**: Excerpts of governing rules and ADRs.
- **Test Zone**: Target pytest suites exercising the slice.
- **Scope Boundary Constraint**: Strict file and symbol boundary declarations.
