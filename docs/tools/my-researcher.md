# MyResearcher — design plan

## Purpose

Given a topic to study — one GitHub issue labeled `my-researcher`, e.g. "Graph
Neural Networks for physics" — **discovers external sources live** (web search +
arXiv), then synthesizes a cited **research brief**: a summary, an annotated
reading list, and prerequisites/learning path. Across a set of topic issues it
also synthesizes a **cross-topic study path** — the order to learn a stack of
otherwise-standalone topics (GNN, RBM, LSTM, Reservoir Computing, …) and why.
Package `myresearcher`, backlog label `my-researcher`.

It is the **discovery + synthesis front** the tool line was missing, and it is
distinct from its three neighbours:

- **MyKnowledger** *answers* a question from a **pre-built** external corpus and
  **never discovers or ingests**. MyResearcher is the opposite direction — it
  goes and *finds* the sources. It may hand a source list to a human to feed
  graphify's (LLM-using) ingest out of band, growing MyKnowledger's corpus, but
  it never ingests itself (same fence MyKnowledger and MyGrapher already hold).
- **MyAdvisor** recommends a *decision* ("should we do X") from project history.
- **my-planner** sequences the *fleet's own build backlog*. MyResearcher's
  `plan` mode sequences *external study topics* — a different corpus and a
  distinct ledger `kind`; the two never collide (see Open questions).

## The single Engine call

Two subcommands, **each a separate invocation making exactly one Engine call** —
the harness's one-call rule holds per run, not per tool.

### `brief` (per topic)

Required: "from these discovered sources, write a study brief for this topic."

- **Input:** the topic issue title + body, plus a deterministically retrieved,
  size-capped shortlist of candidate sources (each: `source_id`, title, authors,
  year, venue/url, abstract or snippet). `context = {"topic_issue": N,
  "source_count": k}`.
- **Output:** `data = {"summary": str, "reading_list": [{"source_id", "why",
  "order"}], "prerequisites": [str], "learning_path": [str]}`. The model may
  **only** cite `source_id`s from the shortlist — no invented sources (same
  discipline as MySearcher's permutation rule and MyKnowledger's cite-only rule).
- Against `NoopEngine`: no synthesis — emits the retrieved sources verbatim as a
  raw annotated list with their citations, same honest degrade as MyKnowledger.

### `plan` (across topics)

Required: "order these already-researched topics into a study path."

- **Input:** the briefs already produced for a set of topic issues
  (deterministically gathered — committed `research/<topic>.md`, else the topic's
  last `kind=research` ledger entry), size-capped. `context = {"topics":
  [N, ...]}`.
- **Output:** `data = {"study_path": [{"topic", "rationale", "prereqs":
  [topic, ...]}], "flags": [...]}` — an ordering + dependency map over the given
  topics only; may not invent topics.
- Against `NoopEngine`: emits the topics in issue order with no rationale —
  plumbing only, explicitly not a meaningful ordering (same caveat as MyAdvisor).

## Deterministic pre-work

### `brief`

1. Read the topic issue (label `my-researcher`).
2. Build search queries from the issue title/body (lowercase, split on
   non-alnum, drop stopwords — the same naive tokenizer MySearcher uses).
3. Retrieve candidates over **LLM-free HTTP** (stdlib `urllib`, no SDK per the
   harness's dependency-free rule):
   - **arXiv API** (Atom REST, **no key**) — the zero-config default.
   - The **configured web-search provider** (pluggable via env, e.g. Tavily/
     Brave/SerpAPI) for technical sites, docs, and books — only if its key is
     set.
4. Normalize + dedupe (by DOI/arXiv-id/url) into one candidate list; cap to the
   top N (default 15) by a deterministic score (recency + query-term overlap),
   bounding the Engine prompt — the same size-cap discipline as every retrieval
   tool in the line.
5. If no web provider is configured, arXiv-only still yields a usable brief. If
   retrieval returns nothing at all, **skip the Engine call** and post "no
   sources found for `<topic>`" — deterministic short-circuit, same as
   MyKnowledger's no-match case.

### `plan`

1. Gather briefs for the given topic issues (`--label my-researcher` or
   `--issues N,M,…`): read committed `research/<topic>.md`, else the topic's last
   `kind=research` ledger `data`.
2. Size-cap the bundle. If fewer than 2 topics resolve, **skip the Engine call**
   and emit the single topic as-is (nothing to order).

## Ledger

- **`brief` writes:** `kind=research`, `outcome=success|skipped`, `detail`="brief
  for `<topic>` (`k` sources)", `data={topic, issue, sources, cited, brief_path,
  pr_url, comment_url}`.
- **`plan` writes:** `kind=study_plan`, `outcome=success|skipped`, `detail`="study
  path over `k` topics", `data={topics, study_path, plan_path, pr_url,
  comment_url}` — a distinct `kind` so plan entries never collide with per-topic
  `research` entries.
- **Reads:** `brief` reads nothing (each topic is independent; re-running is
  allowed — it refreshes, see Guard). `plan` reads prior `kind=research` entries
  to assemble its bundle.

## Guard & Workspace

Both artifacts ship (per the chosen scope), so a run has **two** side effects,
each an `Action(kind="bash", …)` routed through `Policy.evaluate()`, `ALLOW` by
default, **never a merge**:

- **Committed file via `Workspace`** — writes `research/<topic>.md` (brief) or
  `research/STUDY-PLAN.md` (plan) in a worktree and opens a PR carrying
  `Closes #N` — the same `isolation` + PR path MyTester uses. A re-run for an
  existing topic is **idempotent**: it resumes the topic's branch and updates the
  file rather than opening a duplicate PR (same one-PR-per-unit discipline as
  MyTester/MyChangelogger). Never merges.
- **Issue comment** — posts the same brief/plan markdown to the topic issue.

Boundaries and invariants:

- **First live-web tool besides MyTelegramBot.** arXiv needs no key; the
  web-search provider's key is a **CI secret** (`gh secret set`), **never
  committed**. All network is deterministic (no model call) so it stays outside
  the one-Engine-call contract. In the default suite the HTTP boundary is
  **mocked**; any real-network test is `@pytest.mark.slow`.
- **Never ingests a corpus.** MyResearcher emits a cited source list; growing
  graphify/MyKnowledger's corpus from it is a human, out-of-band step — the same
  "never bootstraps, only …" fence MyKnowledger and MyGrapher hold, generalized
  to the discovery direction.

## CLI surface

```
myresearcher brief --issue <number> [--sources arxiv,web] [--top 15] \
                    [--no-pr] [--no-comment]
myresearcher plan  --label my-researcher [--issues N,M,...] [--no-pr]
```

## Test plan

- **`brief` happy path:** a fixture issue + a **mocked** arXiv/web HTTP layer
  returning a few sources; a scripted `Engine` reply with
  summary + reading_list + prerequisites; assert `research/<topic>.md` renders
  the cited brief, a PR is opened (fake `github.Runner`), the comment is posted,
  and `kind=research`/`outcome=success` is written.
- **`brief` edge (no sources):** mocked HTTP returns empty; assert the Engine is
  never called (spy `Engine`), `outcome=skipped`, the "no sources" comment is
  posted, and no PR is opened.
- **`brief` NoopEngine degrade:** assert the raw source list is emitted with
  citations and the run still succeeds.
- **`plan` happy path:** two fixture briefs; scripted `Engine` study_path; assert
  `research/STUDY-PLAN.md` renders the ordering and `kind=study_plan` is written.
- **`plan` edge (<2 topics):** assert the Engine is never called and the single
  topic is emitted unchanged.
- Mock the HTTP boundary (arXiv/web) and `github.Runner`; the retrieval→cite
  shape and file rendering run against real temp fixtures, never mocked. One
  live-network smoke test is `@pytest.mark.slow`.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, and `isolation` (`Workspace` for
the PR path). The retrieval layer is **stdlib-only** (`urllib` + `xml.etree` for
arXiv Atom, `json` for the search provider) — no new runtime SDK, per the
harness. Independent of MyKnowledger (opposite direction, and a natural *producer*
for its corpus). `plan` mode's "order a set with one Engine call" shape rhymes
with my-planner's — over a different corpus (external study vs. fleet backlog) —
a candidate for a shared core helper if a third caller appears, not extracted
speculatively now.

The arXiv path is testable/usable immediately; the web-search path needs its
provider secret wired (`gh secret set <PROVIDER>_API_KEY -R
MyThingsLab/my-researcher`) before it works live. Build order: standalone; slots
alongside or after MyKnowledger.

**Open questions:**

- **Which web-search provider is the default?** Pluggable via env; pick one when
  wiring the secret (Tavily/Brave/SerpAPI all fit the same JSON-REST shape). Not
  decided here; arXiv-only is the zero-config fallback until then.
- **Cache downloaded PDFs, or cite metadata only?** Leaning metadata-only for v0
  — no binary blobs in the repo; a human runs graphify ingest over the cited
  sources out of band if they want MyKnowledger to answer from them later.
- **`plan` vs. my-planner overlap.** The seam is corpus, not shape (external
  study topics vs. the fleet build backlog) and the ledger `kind`s differ; if a
  third "order-a-set" caller appears, promote a shared helper to core rather than
  coupling the two tools.
- **Confirm `kind=research` / `kind=study_plan`** don't collide with an existing
  ledger `kind` before implementation.
