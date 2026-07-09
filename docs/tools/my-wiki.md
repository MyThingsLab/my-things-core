---
tool: MyWiki
repo: my-wiki
package: mywiki
status: designed
added: 2026-07-05
backlog_label: my-wiki
engine_call: answer this question using only these ledger excerpts
ledger_kinds: [wiki]
depends_on: [tool:my-reporter]
---

# MyWiki — design plan

Formerly designed under the name "MyKnowledger" — renamed so that name is
free for the tool that answers domain questions from external literature
(papers, books, the internet). See [my-knowledger.md](my-knowledger.md).

## Purpose

Answers "what happened / why" questions across repos' ledgers, grounded
strictly in *this project's own recorded history*. Package `mywiki`,
backlog label `my-wiki` (consumes a question posted as an issue, answers as
a comment — same shape as MyReporter, but Q&A instead of a digest).

## The single Engine call

Required: "answer this question using only the given ledger excerpts."

- **Input:** `EngineRequest.prompt` = the question (issue title + body)
  plus a deterministically shortlisted set of ledger entries (see pre-work).
  `context = {"question_issue": N, "candidate_count": k}`.
- **Output:** `EngineResult.text` = the answer; `data = {"cited":
  [entry_ts, ...]}` — the entries the answer actually drew on, so a reader
  can jump to the exact `dev-ledger` line. The model may only answer from
  the given excerpts; it may not cite an entry not in the shortlist.
- Against `NoopEngine`: no synthesis — falls back to printing the
  shortlisted entries verbatim as "here's what I found, unsummarized."
  Honest degrade, not a wrong answer dressed as a right one.

## Deterministic pre-work

1. Read the question issue (label `my-wiki`).
2. Merge every configured repo's `Ledger` + `dev-ledger/*.jsonl` streams,
   sorted by `ts` (same aggregation MyReporter already does — worth
   factoring into a shared helper once both exist, see open questions).
3. Keyword/date-match the question against `detail` + `data` fields; take
   the top N (default 30) by overlap as the shortlist — same
   shortlist-then-judge shape as MySearcher and MyReviewer's diff cap, for
   the same reason: bound the Engine prompt, keep the cost predictable.
4. If the shortlist is empty (no term overlap at all), skip the Engine call
   entirely and post "no relevant history found" — a deterministic
   short-circuit, not a model guess from nothing.

## Ledger

- **Writes:** `kind=wiki`, `outcome=success|skipped`, `detail`=the question
  (truncated), `data={question, cited_entries, comment_url}`. (Named
  `wiki`, not `knowledge`, to keep the two RAG-shaped tools' ledger kinds
  from colliding once MyKnowledger also exists.)
- **Reads:** the full merged ledger + dev-ledger stream across every repo
  it's configured to watch (read-only, same as MyReporter).

## Guard & Workspace

- No `Workspace` — read-only over ledgers, no tree edits, no PR.
- The only side effect is `gh issue comment`, an `Action(kind="bash", ...)`
  through `Policy` — resolves `ALLOW` by default under MyGuard's rules,
  same as MyReporter's and MySearcher's comment paths.

## CLI surface

```
mywiki ask --issue <number> [--repos core,my-guard,...]
```

## Test plan

- **Happy path:** fixture ledgers across two repos, one containing a
  `kind=decision` entry whose text matches the question's keywords;
  scripted `Engine` reply citing it; assert the posted comment includes the
  citation and `kind=wiki`/`outcome=success` is written.
- **Edge case (no match):** a question sharing no terms with any entry;
  assert the Engine is never called (verify via a spy `Engine`) and
  `outcome=skipped`.
- Mock only `github.Runner`; ledger merging is exercised against real temp
  JSONL fixtures.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`. Shares its ledger-merging
logic with MyReporter (step 2) — build after MyReporter and consider
whether that merge routine belongs in `my-things-core` once two tools need
it independently (a "promote to core once duplicated" rule worth adopting
generally, see the cross-cutting note in the README). Independent of
MySearcher/MyGrapher for v0 (keyword match is sufficient); designed so a
future revision can swap in graph-based retrieval the same way MySearcher's
doc already flags. Also independent of MyKnowledger — same "shortlist,
then one Engine call to cite an answer" shape, but a different corpus
(project ledger vs. external literature); see the cross-cutting reuse note
in [README.md](README.md).

**Open questions:**
- Which repos MyWiki watches needs a config (a list, presumably in the
  workspace, not per-repo) — not decided; assumed a `--repos` flag for v0
  rather than an implicit "all repos under the org" default, to avoid
  surprise cost/latency as the org grows.
- Whether ledger-merging should be factored into a shared core helper now
  or left duplicated until a third tool needs it — leaving unresolved
  deliberately; premature abstraction after only two callers is exactly
  the kind of thing not worth deciding yet.
