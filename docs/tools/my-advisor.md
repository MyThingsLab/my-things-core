# MyAdvisor — design plan

**Design now, build meaningfully only with a real Engine backend** (like
MyCoder — `NoopEngine` can validate the plumbing but not the judgment).

## Purpose

Recommends a course of action on a posed "should we do X" question,
grounded in ledger history and relevant code, with explicit trade-offs.
Package `myadvisor`, backlog label `my-advisor`.

## The single Engine call

Required: "recommend an answer, with trade-offs, using the given context."

- **Input:** the question issue's title + body, plus a deterministically
  assembled context bundle (see pre-work): related past `kind=decision`
  entries, related files, a size cap on the total prompt (same cap pattern
  as MyReviewer's diff truncation).
- **Output:** `data = {"recommendation": str, "confidence": "low"|"medium"|
  "high", "risks": [str, ...]}`.
- Against `NoopEngine`: a fixed placeholder recommendation with
  `confidence="low"` — enough to exercise context-assembly → Engine call →
  comment plumbing end-to-end, but **explicitly not a meaningful
  recommendation**; this is the one tool in the batch where a passing test
  suite says nothing about output quality.

## Deterministic pre-work

1. Read the question issue (label `my-advisor`).
2. Gather related past decisions: reuse MyWiki's shortlist logic
   (keyword/date match over the merged ledger) — this makes MyAdvisor a
   consumer of MyWiki's approach, see open question below on how
   that reuse should actually be wired.
3. Gather related files: reuse MySearcher's shortlist logic the same way.
4. Cap the combined bundle to a fixed size, trimming lowest-relevance items
   first (deterministic truncation, not a model decision).
5. **Do not skip the Engine call on an empty bundle** — unlike MyWiki,
   a "should we do X" question can be reasoned about with zero prior
   history; an empty bundle is passed through with a note in the prompt
   ("no directly related history found") rather than short-circuiting.

## Ledger

- **Writes:** `kind=advise`, `outcome=success`, `detail`=the question
  (truncated), `data={question, confidence, cited}`.
- **Reads:** same merged ledger + dev-ledger stream as MyWiki, plus a
  file index if MySearcher/MyGrapher is available.

## Guard & Workspace

- No `Workspace` — advisory only, no tree edits, no PR. The only side
  effect is `gh issue comment`, an `Action(kind="bash", ...)` through
  `Policy`, `ALLOW` by default.
- Purely advisory like MyReviewer: a recommendation is markdown on an
  issue, never a blocking gate — a human still decides.

## CLI surface

```
myadvisor ask --issue <number>
```

## Test plan

- **Happy path:** scripted `Engine` reply with a recommendation +
  confidence + risks over a fixture context bundle; assert the posted
  comment renders all three fields and `kind=advise`/`outcome=success` is
  written.
- **Edge case (empty context bundle):** no related decisions or files
  found; assert the Engine is still called (unlike MyWiki) with a
  prompt noting the absence, and the run still succeeds.
- Mock `github.Runner`; the context-assembly reuse of MyWiki/
  MySearcher logic is exercised against real temp fixtures, not mocked.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, plus MyWiki's and
MySearcher's shortlist logic. **Build last** among the seven new tools in
this batch — both because its judgment quality can't be validated against
`NoopEngine` (same reason as MyCoder) and because it depends on two other
tools' retrieval logic existing first.

**Open questions:**
- **Cross-tool reuse mechanism isn't settled.** MyAdvisor wanting
  MyWiki's and MySearcher's shortlist logic raises a real question:
  do `My[X]` tools depend on each other as installed packages (like
  `my-guard` depends on `mythings-core`), or should shared retrieval
  helpers get promoted into `mythings-core` once two or more tools need
  the same logic? The latter keeps tools independent per the harness's
  design (`mythings-core` is the only shared dependency); the former
  couples tool repos to each other. Recommend promoting to core once
  duplication is confirmed (i.e. after MyWiki and MySearcher both
  ship) rather than deciding speculatively now.
- Whether `confidence` should ever gate anything mechanically (e.g. `low`
  confidence auto-CCs a human) — left as a future refinement, not v0.
- Whether the context bundle should also pull from MyKnowledger's external
  literature corpus (papers/books, not just project history) — grounding
  an architectural recommendation in published best practice as well as
  past decisions seems genuinely valuable, but adds a third retrieval
  dependency to an already-last-in-line tool; not added to v0 scope.
