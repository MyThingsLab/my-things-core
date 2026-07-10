---
tool: MyBibliography
repo: my-bibliography
package: mybibliography
status: designed
added: 2026-07-09
backlog_label: my-bibliography
engine_call: resolve a reference request to one canonical candidate, with a citation key
ledger_kinds: [bibliography]
depends_on: []
---

# MyBibliography — design plan

> **Pre-build design plan** — written to think through this tool before its
> repo exists. Once shipped, this doc goes historical: read
> [`my-bibliography/README.md`](../../../my-bibliography/README.md) and
> [`my-bibliography/CLAUDE.md`](../../../my-bibliography/CLAUDE.md) instead.

## Purpose

Given a reference-request issue — a DOI, an arXiv id, an ISBN, or a free-text
title/author query for a paper or book — **discovers canonical citation
metadata live** (Crossref for DOIs/papers, arXiv Atom API for arXiv ids, Open
Library for ISBNs/books), then makes one Engine call to resolve ambiguity and
assign a citation key, and commits a normalized entry to the repo's growing
bibliography (`references.bib` + `references.json`, a CSL-JSON twin), deduping
by DOI/ISBN/arXiv-id. Package `mybibliography`, backlog label
`my-bibliography`.

It is a cataloging tool, not a synthesis tool, and distinct from its three
neighbours:

- **MyResearcher** discovers sources to *learn from* and synthesizes a study
  brief (summary, reading list, prerequisites). MyBibliography discovers a
  *single reference* to *cite* and produces no prose — just a structured
  bibliography entry. Same live-discovery shape, disjoint output.
- **MyKnowledger** answers questions from an already-ingested corpus and never
  discovers. MyBibliography never ingests content or answers questions; it
  only catalogs citation metadata.
- **MyLibrarian** discovers software packages to depend on. MyBibliography
  discovers publication metadata to cite — same "discover, then judge" shape,
  disjoint corpus.

## The single Engine call

Required: "given a reference request and its deterministically retrieved
candidate metadata record(s), choose the canonical one and assign it a
citation key."

- **Input:** the locator/query text, plus a deterministically retrieved,
  size-capped shortlist of candidate records (each: `candidate_id`, `type`
  [`article`|`book`], title, authors, year, venue, doi, isbn, url).
  `context = {"ref_issue": N, "candidate_count": k}`.
- **Output:** `data = {"chosen_candidate_id": str, "key": str, "rejected":
  [{"candidate_id", "why"}], "confidence": "low"|"medium"|"high"}`. The model
  may only **choose** a `candidate_id` from the shortlist and **invent the
  key** — it never supplies title/authors/year/doi/isbn/url itself. The tool
  deterministically copies those fields from the chosen candidate's
  already-retrieved record after the call, the same defensive posture as
  MyResearcher's cite-only rule, applied to field values rather than just
  source ids (a reference entry with a hallucinated year or DOI is worse than
  a missing one).
- Against `NoopEngine`: deterministic degrade — one candidate is chosen
  automatically (`confidence="high"`) with a deterministic key
  (`lowercase(first-author-surname) + year`, collision-suffixed
  `a`/`b`/`c`…); with several candidates, the top-scored by deterministic
  query-term overlap is chosen (`confidence="low"`), the rest listed as
  `rejected` with `why="not the top-scored match"` — same honest-degrade
  posture as MyResearcher/MyLibrarian.

## Deterministic pre-work

1. Read the reference-request issue (label `my-bibliography`). Its body names
   one locator: `doi:`, `arxiv:`, `isbn:`, or `query:` (free-text
   title/author).
2. Retrieve over **LLM-free HTTP** (stdlib `urllib` + `json`/`xml.etree`, no
   SDK, per the harness):
   - `doi:` → Crossref `works/<doi>` (**no key**).
   - `arxiv:` → arXiv Atom API (**no key**) — same client shape as
     MyResearcher's, not the same package (no cross-tool dependency, the same
     fence MyTodo held reading MyPlanner's ledger directly).
   - `isbn:` → Open Library Books API (**no key**).
   - `query:` → Crossref works search **and** Open Library search in
     parallel, merged into one candidate list (a free-text query may resolve
     to a paper or a book — both providers are searched, not chosen upfront).
3. Normalize each hit into a common record: `{candidate_id, type, title,
   authors, year, venue, doi, isbn, url}`.
4. Deterministic dedupe + score (query-term overlap for `query:`, trivial for
   a direct locator) and cap to the top N (default 5) — bounding the Engine
   prompt, same size-cap discipline as every retrieval tool in the line.
5. If retrieval returns **nothing**, **skip the Engine call** and post "no
   metadata found for `<locator>`" — deterministic short-circuit, same as
   MyResearcher's no-sources case. No entry is written.
6. Before calling the Engine, check the existing bibliography file for a
   matching `doi`/`isbn`/`arxiv-id` across all retrieved candidates. If one
   already exists, **skip the Engine call** and post "already in bibliography
   as `<key>`" — idempotent-append, same posture as MyTodo/MyChangelogger.

## Ledger

- **Writes:** `kind=bibliography`, `outcome=success|skipped`, `detail`="entry
  for `<locator>` (`k` candidates)", `data={locator, candidates,
  chosen_candidate_id, key, entry, rejected, confidence, bib_path, pr_url,
  comment_url}`.
- **Reads:** the committed bibliography file only, to dedupe by identifier
  before writing — no other ledger reads.

## Guard & Workspace

Two side effects, each an `Action(kind="bash", ...)` routed through
`Policy.evaluate()`, `ALLOW` by default, **never a merge**:

- **Committed file via `Workspace`** — appends the resolved entry to
  `references.bib` (BibTeX) and `references.json` (CSL-JSON, the
  machine-readable twin other tools can read without a BibTeX parser) in a
  worktree, opens a PR carrying `Closes #N`. Idempotent per identifier: a
  re-run for an already-cataloged reference resumes/skips rather than
  duplicating (same one-PR-per-unit discipline as MyResearcher/MyTester).
- **Issue comment** — posts the rendered BibTeX entry, `confidence`, and any
  `rejected` candidates with their `why`.

## CLI surface

```
mybibliography add --issue <number> [--locator doi:10.xxxx|arxiv:xxxx|isbn:xxxx|query:"..."] \
                    [--top 5] [--no-pr] [--no-comment] [--engine claude-cli]
```

`--locator` overrides the issue body for local testing; normally the locator
is parsed from the issue.

## Test plan

- **Happy path (direct locator):** a fixture issue with `doi:` + **mocked**
  Crossref response (one candidate); a scripted `Engine` reply; assert
  `references.bib`/`references.json` gain the entry, a PR is opened (fake
  `github.Runner`), the comment is posted, `kind=bibliography`/
  `outcome=success` is written.
- **Happy path (ambiguous free-text):** mocked Crossref + Open Library return
  several candidates; scripted `Engine` reply chooses one and rejects the
  rest; assert the entry matches the *chosen candidate's retrieved fields*,
  not anything the mocked Engine reply might additionally claim (field-
  integrity test — the defensive-copy invariant).
- **Edge (no candidates):** mocked HTTP returns empty; assert the Engine is
  never called (spy `Engine`), `outcome=skipped`, the "no metadata found"
  comment is posted, no PR opened.
- **Edge (already cataloged):** a fixture bibliography file already containing
  the resolved DOI; assert the Engine is never called, `outcome=skipped`, the
  "already in bibliography" comment is posted, no duplicate entry.
- **`NoopEngine` degrade:** single-candidate case auto-chooses with
  `confidence="high"`; multi-candidate case chooses the top-scored with
  `confidence="low"` and the rest as `rejected`.
- Mock the HTTP boundary (Crossref/arXiv/Open Library) and `github.Runner`;
  one live-network smoke test is `@pytest.mark.slow`, same convention as
  MyResearcher.

## Not in scope (v0)

Fetching or storing PDFs/full text (metadata only, same decision MyResearcher
made); citation-style rendering (APA/MLA) beyond BibTeX/CSL-JSON — a
downstream typesetting concern for MyTypster; scanning a paper/draft for
`\cite{}` keys and cross-checking them against the bibliography (a plausible
v1 follow-up, not v0); deduping across bibliography files in *different*
repos — one bibliography file per repo instance.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation` (`Workspace` for the
PR path). The retrieval layer is **stdlib-only** (`urllib` + `json` for
Crossref/Open Library, `xml.etree` for arXiv Atom) — no new runtime SDK, per
the harness. Independent of every other tool; slots in alongside
MyResearcher/MyLibrarian (same discovery family, disjoint corpus: citation
metadata vs. study sources vs. software packages).

**Open questions:**

- **Crossref politeness pool.** Sending a `mailto:` in the User-Agent gets a
  faster, more reliable pool; not required to function. Pick the contact
  address at implementation time.
- **BibTeX key collision suffix scheme** (`a`/`b`/`c` vs. `-2`/`-3`) — decide
  at implementation; either satisfies uniqueness.
- **ISBN-10 vs. ISBN-13 normalization** for Open Library dedup — likely
  normalize to ISBN-13 at implementation to avoid two records for the same
  book.
