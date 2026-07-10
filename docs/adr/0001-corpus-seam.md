# ADR 0001 — the shared "shortlist-from-a-corpus-then-cite" seam

- **Status:** proposed
- **Date:** 2026-07-10
- **Issue:** [my-things-core#36](https://github.com/MyThingsLab/my-things-core/issues/36)

## Context

Ten designed tools independently want the same capability: *shortlist the few
relevant items from a corpus, then answer with citations.*

- **Code corpora** (named in #36): MyWiki, MySearcher, MyAdvisor, MyDescriber,
  MyKnowledger.
- **Document corpora** (the study cluster): MyGlossary, MySyllabus, MyProfessor,
  MyFlashcards, MyGrader.

#36 offered two options: a tool-to-tool package dependency (as `my-guard` →
`mythings-core`), or promotion into core as a small `select`/`cite` seam.

## Decision

**Promote into core**, as `mythings.corpus`.

A tool-to-tool dependency would make ten repos depend on whichever consumer
happened to be built first, inverting the fleet's dependency direction. The
pattern is not merely duplicated — it is decupled.

**The seam serves _document_ corpora. `my-searcher`'s file-granularity
`shortlist()` stays exactly as it is.**

This scoping is the substantive part of the decision. `my-searcher`'s
`shortlist()` (`my-searcher/src/mysearcher/indexer.py:85`) scores at **file**
granularity over **path and identifier tokens only** — it never reads body text.
That is *correct* for code, where filenames and symbol names carry the signal.
It is useless for a study corpus: a 400-page textbook is one file named
`bishop-prml.pdf` and scores zero against every query.

So `mythings.corpus` is a **new module, not a generalization** of that function.
It reuses `tokenize()` (recopied, ~5 lines, rather than triggering a cross-repo
refactor) and the degrade-to-a-weak-ranking-rather-than-an-empty-result
discipline. It adds what code search never needed: **chunking** and **body-text
scoring**.

Promising the five code tools a migration onto this seam would be a check it
cannot cash. They may adopt it later, on their own schedule, if their corpora
ever become prose.

## The API

```python
ingest(paths, *, extractor=extract) -> list[Document]   # Document(id, path, title, text)
chunk(doc, *, target_chars=1200)    -> list[Chunk]      # Chunk(doc_id, ordinal, text, start, end)
shortlist(chunks, query, *, top=8)  -> list[Chunk]
cite(chunks, documents)             -> list[Citation]   # Citation.marker() -> "[doc_id:ordinal]"
```

Three properties keep a new module in the SDK every repo depends on tolerable,
and the implementation must preserve all three (the same three that made
`mythings.testers` acceptable):

1. **Zero new dependencies.** Core declares `dependencies = []`. PDF text
   extraction shells out to `pdftotext` (poppler) through an injected
   `Extractor = Callable[[Path], str]` — exactly the `github.Runner` precedent,
   where `Runner = Callable[[list[str]], str]` shells out to `gh`. A system
   binary is not a Python package, and a caller injects a pure extractor in tests.
2. **No import-time side effects.** Nothing opens a file or touches the network
   until a caller passes an explicit path, mirroring `Ledger(path)`.
3. **Inert by default.** No tool reads it unless it opts in.

### Chunks tile; they do not overlap

Overlapping windows are standard for embedding retrieval, and wrong here.
Token-overlap scoring gains nothing from overlap, and overlapping spans would let
one claim cite two chunks containing the same sentence. `Chunk.start`/`.end` are
character offsets into `Document.text`, so a `Citation` resolves back to the
exact span a claim came from — verified against the real corpus, where all 146
chunks of Ghahramani's *Unsupervised Learning* round-trip
`doc.text[c.start:c.end] == c.text`.

### Ranking degrades rather than returning nothing

When no chunk scores above zero (or the query carries no usable tokens),
`shortlist()` returns the leading chunks in document order. `my-searcher` falls
back to most-recently-modified files; that signal is meaningless for chunks of
one document.

## Known limitation — ranking is raw token overlap

Verified on the real corpus (`~/Desktop/unsupervised_learning.pdf`, 41pp):

- The **abstract ranks top-3 for every query**. It name-drops every topic in the
  paper, so raw overlap of distinct query tokens favours it. A generic magnet.
- A **bibliography entry** matched `"EM algorithm"` because a reference *title*
  contains those words — a consumer would cite the reference list as the source
  of a definition.

The fix is **IDF weighting** (rare tokens count for more), which stays
deterministic and dependency-free. It is deliberately **not** in the first cut:
it changes the ranking contract, and the contract should be changed on purpose,
with a consumer exercising it. Tracked as a follow-up; `my-glossary` is the tool
that will show whether it matters in practice.

## Consequences

- `my-glossary` is built next as the **thinnest possible consumer**, to exercise
  the contract before four more study tools depend on it. The full study cluster
  was explicitly deferred for this reason.
- `my-searcher` is untouched. No cross-repo fan-out.
- Tools needing PDFs require `poppler-utils` on the host; a pure-Python or
  `pdftotext`-free consumer injects its own `Extractor`.
