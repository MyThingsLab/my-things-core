# MyLibrarian — design plan

## Purpose

Given a task ("convert Markdown to HTML", "typeset a PDF", "parse YAML"),
**discovers existing community-maintained libraries/CLIs live** (PyPI, npm,
GitHub) and recommends which one(s) to reach for instead of reimplementing —
e.g. `markdown-it`/`pandoc` for document conversion. A build-vs-buy check
that runs *before* MyCoder (or a human) writes new code, not a research
brief and not a project-history recommendation. Package `mylibrarian`,
backlog label `my-librarian`.

Distinct from its three neighbours, each a "discover/retrieve, then judge"
shape over a different corpus:

- **MyResearcher** discovers external *sources* (papers, articles, docs) to
  *learn from* — output is a study brief. MyLibrarian discovers external
  *software packages* to *depend on* — output is a build-vs-buy
  recommendation with an install/usage snippet. Same live-discovery shape,
  disjoint corpus and disjoint output.
- **MyAdvisor** recommends a decision grounded in *this project's own*
  ledger/code history. MyLibrarian's grounding is live *public package
  registries* — it never reads the calling repo's history, so it never
  competes with MyAdvisor for the same question.
- **MySearcher** ranks files *within* a repo it already has. MyLibrarian
  searches *outside* the repo entirely, before any file exists to rank.

## The single Engine call

Required: "given this task and a shortlist of discovered candidate
packages, recommend which one(s) to use, with trade-offs and a usage
snippet."

- **Input:** the task issue's title + body, plus a deterministically
  retrieved, size-capped shortlist of candidate packages (each: `name`,
  `registry`, description/summary, license, a popularity signal
  [downloads or stars], last-release date). `context = {"task_issue": N,
  "candidate_count": k}`.
- **Output:** `data = {"recommended": [{"name", "registry", "why",
  "install", "snippet"}], "avoid": [{"name", "why"}], "confidence":
  "low"|"medium"|"high"}`. The model may only recommend or flag names
  present in the shortlist — no invented packages (same discipline as
  MySearcher's permutation rule and MyResearcher's cite-only rule).
- Against `NoopEngine`: no synthesis — emits the shortlist verbatim, sorted
  by the deterministic popularity score, with no `why`/`snippet` — same
  honest degrade as MyResearcher's brief.

## Deterministic pre-work

1. Read the task issue (label `my-librarian`).
2. Build search queries from the issue title/body (lowercase, split on
   non-alnum, drop stopwords — the same naive tokenizer MySearcher and
   MyResearcher already use).
3. Retrieve candidates over **LLM-free HTTP** (stdlib `urllib`, no SDK per
   the harness's dependency-free rule), from whichever registries are
   selected (`--registries`, default `pypi,npm`):
   - **PyPI JSON API** (`pypi.org/pypi/<name>/json` search via
     `pypi.org/search` scrape is unreliable — use the simple index plus a
     curated seed-term search; see open question below) — **no key**.
   - **npm registry search API** (`registry.npmjs.org/-/v1/search`) — **no
     key**.
   - **GitHub code/repo search** via the existing `github.GitHub` wrapper
     (reuses the fleet's already-configured token) — optional, only when
     `github` is in `--registries`.
4. Normalize into one candidate list (`name`, `registry`, description,
   license, popularity signal, last-release date) and score deterministically:
   query-term overlap + popularity + recency, with an explicit downrank (not
   a drop) for copyleft licenses so the Engine call sees them but is
   steered away — cap to the top N (default 10), bounding the Engine
   prompt, same size-cap discipline as every retrieval tool in the line.
5. If retrieval returns nothing across all selected registries, **skip the
   Engine call** and post "no candidates found for `<task>`" — deterministic
   short-circuit, same as MyResearcher's no-sources case.

## Ledger

- **Writes:** `kind=library_survey`, `outcome=success|skipped`,
  `detail`="`k` candidates for `<task>`",
  `data={task_issue, task, candidates, recommended, avoid, comment_url}`.
- **Reads:** nothing — each survey is independent; re-running refreshes
  rather than erroring (same posture as MyResearcher's `brief`).

## Guard & Workspace

Read-only over the calling repo — no `Workspace` worktree, no PR, no code
edits (MyLibrarian recommends, it never adopts a dependency itself). The
only side effect is an issue comment rendering `recommended`/`avoid`/
`confidence`, an `Action(kind="bash", ...)` routed through `Policy`
(`ALLOW` by default, same as MySearcher's `--comment` path). Writes exactly
one `kind=library_survey` ledger entry per run.

## CLI surface

```
mylibrarian survey --issue <number> --task "<query>" \
                    [--registries pypi,npm,github] [--top 10] \
                    [--no-comment] [--engine claude-cli]
```

## Test plan

- **Happy path:** a fixture issue + **mocked** PyPI/npm HTTP responses
  returning a few candidates; a scripted `Engine` reply with
  `recommended`/`avoid`/`confidence`; assert the comment renders all three
  fields and `kind=library_survey`/`outcome=success` is written.
- **Edge (no candidates):** mocked HTTP returns empty for every selected
  registry; assert the Engine is never called (spy `Engine`),
  `outcome=skipped`, the "no candidates" comment is posted.
- **`NoopEngine` degrade:** assert the raw, popularity-sorted shortlist is
  emitted with no fabricated `why`/`snippet` and the run still succeeds.
- **License downrank:** a fixture where a copyleft-licensed candidate
  outscores an MIT one on raw popularity; assert it still appears in the
  shortlist (never silently dropped) but ranked below the permissive
  option.
- Mock the HTTP boundary (PyPI/npm) and `github.Runner`; one live-network
  smoke test is `@pytest.mark.slow`, same convention as MyResearcher.

## Not in scope (v0)

Actually adding the recommended dependency to any repo (a human, or later
MyCoder, does that as a separate, reviewable step); comparing versions of a
package already in use (that's a dependency-upgrade concern, not
discovery); non-code artifacts (fonts, datasets) — packages/CLIs only.

## Dependencies & build order

Depends on core `ledger`, `github` (comment path; optional GitHub-search
registry), `policy`. The retrieval layer is **stdlib-only** (`urllib` +
`json`) — no new runtime SDK, per the harness, same posture as
MyResearcher. Independent of every other tool; slots in alongside
MyResearcher/MyKnowledger (same discovery family) — no ordering
dependency.

**Open questions:**

- **PyPI has no first-party free-text search endpoint** (the old
  `pypi.org/search` JSON endpoint was retired). v0 options: query a
  small curated seed list of well-known packages per common task keyword
  (markdown → `markdown-it-py`, `mistune`; docs → `pandoc`/`pypandoc`,
  `sphinx`), falling back to GitHub code search for anything not in the
  seed list. Not decided here — pick when implementation starts.
- **License data quality.** PyPI/npm metadata's `license` field is
  free-text and inconsistent; a best-effort normalizer (SPDX-id match,
  else "unknown") is enough for v0 — never block a recommendation on
  unparsed license text, just surface it verbatim in `why`.
