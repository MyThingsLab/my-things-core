---
tool: MyCartographer
repo: my-cartographer
package: mycartographer
status: building
added: 2026-07-12
backlog_label: my-cartographer
engine_call: label each induced cluster and order the themes into a prerequisite DAG
ledger_kinds: [topic_map]
depends_on: []
---

# MyCartographer — design plan

## Purpose

Given a corpus of documents a human already has on disk (a shelf of PDFs, a
notes folder, an EPUB collection), induces the **latent themes across the whole
corpus** and emits a checked-in **topic map**: `topics/topics.json` (the source
of truth) + `topics/TOPICS.md` (human-browsable, with a prerequisite graph).
Each theme carries a name, a one-line blurb, the member documents (a document
may belong to several themes — a textbook spans many), and its prerequisite
edges to the other themes. Package `mycartographer`, backlog label
`my-cartographer`.

It answers the one question the study cluster cannot yet ask: *"what is
actually **in** my collection, and in what order should I approach it?"* —
the eight latent themes across a physics shelf, and the prerequisite DAG
between them, read straight off the material rather than prescribed.

MyCartographer is built directly on **`mythings.corpus`** (ADR 0001): it reuses
`ingest`/`chunk`/the TF-IDF machinery as its read side, and adds one thing that
seam deliberately left out — **clustering**. `corpus.shortlist` ranks chunks
*against a query*; MyCartographer has no query, it groups chunks *against each
other*. That grouping is deterministic pre-work; the single Engine call only
names and orders the groups it finds.

**Distinct from three tools it will be confused with** — the same
confirm-the-corpus-and-output-differ check that caught my-designer/my-fact-check:

- **Not MyUni.** MyUni is **top-down**: it takes a *field name* ("Classical
  Mechanics") and decomposes it into a curriculum from the model's own
  knowledge of the field — prescriptive, "what you *should* study." My
  Cartographer is **bottom-up**: it takes the *documents you actually have* and
  induces the themes present in them — descriptive, "what your materials
  *contain*." They are duals: MyUni tells you what's missing from your shelf;
  MyCartographer tells you what's on it. A later bridge could diff the two, but
  neither absorbs the other (different input, different verb).
- **Not MyGrapher.** MyGrapher wraps the external `graphify` skill to maintain a
  fine-grained node/edge knowledge graph and is **LLM-free by construction**,
  refusing to bootstrap. MyCartographer does its own coarse **thematic**
  clustering over `mythings.corpus` vectors (no `graphify` dependency) and makes
  exactly one required Engine call to *name* what it found. Graph vs. map:
  graphify traces how specific entities connect; MyCartographer partitions a
  corpus into a handful of navigable regions. (See the naming-collision note in
  the README — both read as "map"-flavoured, like MyArchivist/MyLibrarian.)
- **Not MyKnowledger.** MyKnowledger *answers a question* by citing from an
  existing graph. MyCartographer *produces the map* a human (or MyKnowledger)
  then navigates. Retrieve-and-cite vs. survey-and-organize.

## The single Engine call

Required: "label each induced cluster and order the themes into a prerequisite
DAG." One batched call per run — not one per cluster — over the *k* deterministic
clusters, mirroring MyUni's single decompose-and-order call rather than a
call-per-item loop.

- **Input:** each cluster represented deterministically by its top-N
  IDF-weighted terms plus its single most-central chunk excerpt (the chunk
  nearest the cluster centroid) — never the whole cluster, so the prompt stays
  size-capped like every other retrieval tool's shortlist. `context =
  {"cluster_count": k, "doc_count": d}`.
- **Output:** `data = {"themes": [{"cluster": int, "label": str, "blurb": str,
  "prereqs": [cluster_id, ...]}]}` — `cluster` is the numeric id of the
  deterministic cluster being named (permutation-only: every id echoed back must
  be one that was sent, never invented, same discipline as MySearcher's reorder
  rule), and `prereqs` may only reference cluster ids from within the same set
  (no forward reference to a cluster that wasn't provided — the same closed-set
  rule MyUni applies to topic prereqs).
- Against `NoopEngine`: each theme is labelled by its own top term (e.g.
  `label="manifold"`, from the deterministic term ranking), `blurb=""`, and
  `prereqs=[]`; the themes fall back to size-descending order. The map is still
  produced in full — the clustering, membership, and citations are all
  deterministic; the Engine call only supplies names, prose, and the ordering.
  Same honest degrade as every tool: no invented structure, just an unnamed map.

## Deterministic pre-work

1. **Resolve the corpus.** `--corpus <dir>` (repeatable) walks for
   `.pdf/.epub/.md/.txt`; alternatively `--from-catalog <catalog.json>` reads
   the digital-file list MyArchivist already cataloged (loose coupling through
   its artifact, no code dependency — the same issue/artifact coupling MyUni has
   with MyResearcher). At least two documents are required; fewer is a
   `outcome=skipped` no-op (nothing to cluster).
2. **Ingest + chunk** via `mythings.corpus.ingest(paths, extractor=...)` and
   `corpus.chunk(doc)`, wrapping the extractor in `corpus.cached_extractor` so a
   re-map of a large shelf re-extracts only files that changed — the same
   size/mtime-keyed cache the seam already ships.
3. **Vectorize** each chunk into a sparse TF-IDF vector using the seam's own
   tokenizer and smoothed IDF (see *Dependencies* on promoting these internals).
4. **Cluster deterministically.** Agglomerative (average-linkage) clustering over
   **cosine distance**, cut at *k* clusters, with `(doc_id, ordinal)` tie-breaks
   at every merge so the partition is **byte-stable across runs** — determinism
   is non-negotiable here for the same reason every other tool's pre-work is
   deterministic (a map that reshuffles on re-run is a map you can't trust or
   diff). Agglomerative, not k-means: k-means needs a random seed and its result
   drifts; agglomerative with a fixed tie-break is a pure function of the input.
   *k* defaults to `clamp(round(sqrt(doc_count)), 3, 12)`, overridable with
   `--themes k` — deterministic, and it doesn't trust the model to decide how
   many themes a corpus has (the same "don't trust the model's enthusiasm for
   size" stance as MyUni's curriculum cap).
5. **Roll chunk clusters up to document membership.** A document belongs to a
   theme when at least `m` of its chunks fall in that cluster (default `m=2`), so
   a multi-topic textbook honestly appears under several themes rather than being
   forced into one. A document with no qualifying theme is listed under an
   explicit `unassigned` bucket, never dropped.
6. **Represent each cluster** for the Engine call: its top-N IDF-weighted terms
   and its most-central chunk (nearest the centroid), carrying that chunk's
   `Citation` so the label can be traced back to the exact span it came from.

## Deterministic post-work

1. **DAG-repair the prereq edges.** The model returns `prereqs` per theme; drop
   any edge that would introduce a cycle (Kahn's algorithm; on a back-edge, drop
   the later-of-the-two by cluster id) — the same topological-repair the
   `mythings.selection` seam owns for ordered output, applied to the theme graph
   instead of a linear sequence. The map is guaranteed acyclic before it renders.
2. **Render the artifacts:**
   - `topics/topics.json` — `{generated_at, corpus_paths, themes: [{id, label,
     blurb, top_terms, doc_ids, chunk_refs: [{doc_id, ordinal, start, end}],
     prereqs: [id]}], unassigned: [doc_id, ...]}`.
   - `topics/TOPICS.md` — a Mermaid prerequisite graph of the themes, then one
     section per theme (label, blurb, member documents each linked by
     `Citation.marker()` back to the central span), rendered *from* `topics.json`
     exactly as MyArchivist renders `CATALOG.md` from `catalog.json`.
3. **Diff for idempotency:** if `topics.json` is byte-identical to the existing
   one (unchanged corpus, unchanged clustering), the run is `outcome=skipped`
   with no PR — same no-empty-PR discipline as MyArchivist/MyResearcher/MyTodo.

## Ledger

- **Writes:** `kind=topic_map`, `outcome=success|skipped`, `detail`="mapped `d`
  docs into `k` themes (`e` prereq edges)", `data={corpus_paths, doc_count,
  chunk_count, theme_count, edge_count, unassigned_count, pr_url}`.
  `outcome=skipped` covers both the "under two documents" short-circuit and the
  "no change since last map" idempotent re-run.
- **Reads:** the existing `topics/topics.json`, to diff against for idempotency —
  never mutated in place; the new map is written in a `Workspace` and PR'd.

## Guard & Workspace

A topic map is **durable curriculum content**, so it lands **via PR**, not a
local ledger — the hybrid boundary ADR 0002 drew for the study cluster (only
per-answer *mastery* is a local JSONL ledger; anything that is a durable study
artifact — a syllabus decomposition, a research brief, a topic map — goes through
issue→PR→CI). MyCartographer writes `topics/` inside an `isolation.Workspace`
worktree and opens exactly one PR per run (resuming the run's branch on a re-run
before merge, same idempotency pattern as MyTester/MyArchivist).
`Action(kind="bash", ...)` routed through `Policy`, `ALLOW` by default — a
non-destructive data/doc PR, never a merge. No triggering issue in the common
(local `map`) path; an optional `--issue N` lets a human request a remap through
the usual issue-driven path and comments the result there, for consistency with
the rest of the fleet.

## CLI surface

```
mycartographer map [--corpus <dir> ...] [--from-catalog <catalog.json>] \
                   [--themes k] [--min-chunks m] [--cache <dir>] \
                   [--repo owner/name] [--issue N] [--no-pr] \
                   [--engine claude-cli]
```

## Test plan

- **Happy path:** a fixture corpus of ~6 short text docs seeded into three
  obvious lexical clusters (e.g. "linear algebra" / "thermodynamics" /
  "neural networks" vocabularies) + a fake Engine returning labels and a valid
  prereq order; assert `topics.json`/`TOPICS.md` render three themes with the
  right membership, and a single PR opens (fake `github.Runner`),
  `kind=topic_map`/`outcome=success`.
- **Determinism:** run the map twice over the identical corpus; assert
  `topics.json` is **byte-identical** both times (guards the deterministic
  clustering + tie-break — the property the whole design rests on).
- **Cycle repair:** a fake Engine that returns a prereq edge set containing a
  cycle; assert the rendered map is acyclic and the dropped edge is the
  deterministic one, and that `edge_count` in the ledger reflects the repair.
- **Multi-theme membership:** a fixture document whose chunks split across two
  clusters (≥`m` in each); assert it appears under **both** themes, not
  arbitrarily one.
- **`NoopEngine` degrade:** assert the full map is still produced — clusters,
  membership, and citations present — with each theme labelled by its top term,
  empty blurbs, and size-descending order.
- **Skipped cases:** a one-document corpus → `outcome=skipped`, no PR; a re-run
  over an unchanged corpus → `outcome=skipped`, no second PR.
- Mock only `github.Runner`; ingest/chunk/vectorize/cluster all run against real
  fixture files, never mocked (same "mock the boundary, not the logic" rule as
  MyArchivist).

## Not in scope (v0)

- **Semantic (embedding) vectors.** v0 clusters over lexical TF-IDF, the same
  deliberate lexical choice `mythings.corpus` made — good enough to separate a
  thermodynamics chunk from a neural-network one by vocabulary. A real embedding
  backend is a separate, Engine-adjacent decision (where do vectors come from,
  at what cost) and rides on whatever the corpus seam adopts, not invented here.
- **Incremental re-clustering.** v0 re-clusters the whole corpus each run
  (average-linkage is O(n²) in chunks — fine at personal-shelf scale, flagged as
  the first thing to revisit if a corpus grows into the tens of thousands of
  chunks, at which point a deterministic mini-batch approach or a distance-
  threshold cut replaces the fixed-k dendrogram cut).
- **Writing prereq edges back into MyUni issues.** The map→curriculum bridge
  (open a `my-uni`/`my-researcher` issue per unassigned or thin theme) is a
  natural follow-up, but it couples two tools' side effects and belongs in its
  own decision, not this doc.
- **Near-duplicate document detection.** Two editions of the same textbook will
  cluster together (correctly) but aren't deduped into one; that's a MyArchivist
  cataloging concern, not a mapping one.

## Dependencies & build order

Depends on core `corpus` (ingest/chunk + its tokenizer/IDF math), `ledger`,
`policy`, `isolation` (`Workspace` for the PR path), and `github` (PR open +
optional `--issue` comment). The **clustering itself is stdlib-only**,
hand-rolled the same way `corpus` hand-rolls TF-IDF rather than pulling
`numpy`/`scikit-learn` — honoring the dependency-free-runtime rule; a sparse
cosine over token-count dicts needs no matrix library at personal-shelf scale.
Independent of every other tool (soft-consumes MyArchivist's `catalog.json` when
present, but takes `--corpus` directly otherwise).

**Promote-to-core trigger.** MyCartographer is currently the only caller that
needs chunk **vectorization + clustering**. It reaches into `corpus`'s private
`_term_freq`/`_idf`; if a second and third consumer appear (MyProfessor wanting
theme-grouped quizzing, MySyllabus wanting the same partition), promote a
`corpus.vectors(chunks)` + `corpus.cluster(vectors, k)` pair into core under the
≥3-caller rule ADR 0001 set — until then the clustering stays tool-side and only
the tokenizer/IDF internals are candidates for being made public.

**Open questions:**

- **Default target repo.** Like MySite/MyArchivist, the map lives in a personal
  repo (e.g. `lorenzoliuzzo/study` or the same repo MyArchivist catalogs into) —
  configurable, no fleet-wide default; pick the destination when implementation
  starts.
- **Lexical vs. embedding vectors** — settled as lexical for v0 above, but the
  first real stress test on dense math/physics PDFs (where two chapters share
  heavy notation vocabulary yet cover different topics) is what should decide
  whether the lexical signal holds or an embedding backend is worth the cost.
- **Chunk-level vs. document-level clustering, and the membership floor `m`.**
  v0 clusters chunks and rolls up (a textbook spans themes); a `--granularity
  document` mode that clusters whole documents is simpler but coarser. Start with
  chunks; expose `--min-chunks` and revisit the default once run on real material.
- **One combined Engine call vs. two (label, then order).** Folded into one here,
  mirroring MyUni; if the combined label-and-order call's ordering quality
  suffers on real corpora, split `order` into a separate subcommand that reuses
  `mythings.selection.ordered_selection` over the already-labelled themes.
- **Convergence with MyGrapher.** When a `graphify-out/` graph already exists for
  a corpus, its community detection is a second source of clusters; whether
  MyCartographer should *consume* those communities instead of re-clustering
  (turning it into a namer/orderer over graphify's partition) is a possible
  later unification, not v0 — v0 stays graphify-independent so it works on a bare
  folder of PDFs with no graph bootstrapped.
