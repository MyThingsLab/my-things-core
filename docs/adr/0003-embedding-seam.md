# ADR 0003 — the semantic-embedding seam, hybrid with lexical retrieval

- **Status:** Accepted (2026-07-12)
- **Related:** [ADR 0001](0001-corpus-seam.md) (the lexical corpus seam this extends)

## Context

`mythings.corpus` (ADR 0001) scores relevance by lexical TF-IDF. Run against the
real study corpus (19 MyResearcher briefs — physics + a full unsupervised-learning
course, ~224 chunks) exactly as a tool would, it works for literal-vocabulary
queries and **fails in four ways nothing lexical can fix**:

1. **Notation is invisible.** The tokenizer is `[a-zA-Z0-9_]+`, so `∇·σ = 0`
   tokenizes to `['0']` and the k-means objective `‖x_i − μ_k‖²` to `['_k','x_i']`.
   Every math symbol carries zero retrieval signal — fatal for physics material.
2. **Paraphrase misses.** *"splitting data into natural groups by similarity"*
   (i.e. clustering) top-ranked a **Bayesian-networks** chunk, because the word
   "clustering" was not literally in the query.
3. **Vocabulary gaps.** `eigenvalue` has document-frequency **0/224** — the
   concept lives only in notation and paraphrase, so a query for it returns noise.
4. **Cross-language total miss.** An Italian query (*"apprendimento non
   supervisionato…"* — the user's UL materials are Italian) retrieved a **physics**
   doc via a stray shared `"non"`. Lexical overlap across languages is ~zero.

These are measured, not hypothesized. The fix is a representation where nearness
is *meaning* rather than *shared tokens*: text embeddings.

## Decision

**Promote into core**, as `mythings.embed` — the semantic sibling of the Engine
seam, with the identical shape that makes a core dependency tolerable:

- **`Embedder`** — a `Protocol`: `embed(texts) -> list[Vector]` (`Vector` is a
  `tuple[float, ...]`).
- **`HashingEmbedder`** — the dependency-free deterministic default, the
  **NoopEngine analog**. Feature-hashes tokens into a fixed-dim L2-normalized
  vector. It makes every consumer runnable and testable with no network and no
  tokens, and it is what an `ApiEmbedder` failure degrades to. It is deliberately
  **not** semantic (hashing shares no bucket between synonyms) — its job is to
  keep the pipeline whole, not to fix the four gaps. Only a real backend does that.
- **`ApiEmbedder`** — the real backend, over an **OpenAI-compatible
  `/v1/embeddings` endpoint** (the shape OpenAI, llama.cpp, Ollama and LM Studio
  all expose). It **adds no Python dependency** — stdlib `urllib`, the embedding
  analog of `ClaudeCLIEngine` shelling out to a CLI. URL/model/key come from the
  environment (`MYTHINGS_EMBED_URL` / `_MODEL` / `_KEY`). **It never raises:** any
  transport/HTTP/parse failure — or no URL configured at all — degrades to the
  `fallback` embedder, the same honest degrade as `ClaudeCLIEngine` returning an
  empty result.
- **`CachingEmbedder`** — content-addressed disk cache (embeddings are a pure
  function of `(text, model/tag)`; re-clustering re-embeds identical chunks), the
  `CachingEngine` analog: opt-in, inert, stdlib only.
- **`cosine(a, b)`** — the one pure helper consumers need.

**Retrieval fuses the two signals, opt-in.** `corpus.shortlist` gains an optional
`embedder=` parameter. With none, it is **byte-for-byte the original lexical
behaviour** — wiring embeddings in never changes a caller that did not ask.
With one, it combines the lexical ranking and the cosine ranking by
**reciprocal-rank fusion** (the standard `k=60`). Fusing *rank positions*, not the
raw TF-IDF and cosine scores, sidesteps the fact that the two live on different,
incomparable scales — there is no normalisation constant to tune.

## The API

```python
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[Vector]: ...

HashingEmbedder(*, dim=256)
ApiEmbedder(*, url=None, model=None, api_key=None, poster=..., fallback=None, batch=64)
CachingEmbedder(delegate, cache_dir, *, tag="")
cosine(a: Vector, b: Vector) -> float

# hybrid, opt-in, behaviour-preserving:
corpus.shortlist(chunks, query, *, top=8, embedder: Embedder | None = None)
```

It preserves the three properties that make a core module every repo depends on
tolerable (ADR 0001):

1. **Zero new dependencies.** `HashingEmbedder`/`cosine` are pure stdlib;
   `ApiEmbedder` uses stdlib `urllib`. Core stays `dependencies = []`.
2. **No import-time side effects.** Nothing touches network or disk until a
   caller constructs a backend and calls `embed`, mirroring `Ledger(path)` and
   `corpus.cached_extractor`.
3. **Inert and behaviour-preserving by default.** No retrieval changes unless a
   caller passes an `embedder`; `shortlist`'s default path is unchanged.

## Why

- **The gaps are real and measured, not a hunch.** The four failure modes above
  are the concrete case; a lexical-only seam cannot close any of them.
- **Same seam shape as Engine, for the same reasons.** A Protocol with a
  deterministic default + a shell-out/HTTP-out real backend keeps core
  dependency-free and every consumer testable before a backend exists — the exact
  property `engine` already gives the fleet.
- **Hybrid, not replacement.** Lexical TF-IDF still wins on exact identifiers and
  rare literal terms; embeddings win on paraphrase/notation/language. RRF keeps
  both, so no query class regresses.
- **A local endpoint keeps material private.** An OpenAI-compatible URL can be a
  localhost model server, so the corpus never leaves the machine — the same
  privacy posture the fleet already prefers for personal data.

## Consequences

- **MyCartographer is the first consumer** — its deterministic clustering runs
  over `embed` vectors, tightening the fuzzy lexical cluster boundaries the same
  stress test exposed (physics docs cohered at only ~0.12 cosine lexically).
  It relies on `HashingEmbedder` for its zero-token default and gains real
  thematic separation once an `ApiEmbedder` URL is configured.
- **MyKnowledger / MyProfessor** get retrieval-grade Q&A by passing an
  `embedder` to `shortlist`; this is the addition that makes cross-language and
  notation-heavy questions answerable at all.
- **`corpus`'s private vectorization is not promoted yet.** `embed` is the vector
  seam; if a second/third consumer needs corpus-level clustering primitives,
  promote `corpus.vectors`/`corpus.cluster` under the ≥3-caller rule, not before.
- **Picking a concrete default model/endpoint stays an opt-in, per-deployment
  decision** — like `ClaudeCLIEngine(model=...)`, never baked into core.
