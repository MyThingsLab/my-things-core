---
tool: MyPlanner
repo: my-planner
package: myplanner
status: shipped
added: 2026-07-07
backlog_label: my-planner
engine_call: required: propose a sequence, with rationale
ledger_kinds: [plan]
depends_on: [tool:my-orchestrator]
---

# MyPlanner — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-planner's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-planner/README.md`](../../../my-planner/README.md) and
> [`my-planner/CLAUDE.md`](../../../my-planner/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


**Name tentative**, see [my-projector.md](my-projector.md)'s note — nothing
built yet, renaming is free.

**Read this doc's Cross-cutting note in [README.md](README.md) before
building** — this tool's authority boundary against MyOrchestrator and
MyAdvisor is the whole point of it, not an afterthought.

## Purpose

Produces and maintains a **priority-ordered, multi-item plan** — "here's
the recommended order for the next several units of work, and why" —
grounded in the full backlog (unbuilt tools' dependency graph, open
core-contract decisions, safety gaps, recent ledger velocity). Package
`myplanner`, no backlog label of its own (same reason as MyOrchestrator:
it reads every other tool's/repo's backlog rather than being fed one).

**Explicitly not** a duplicate of two things that already exist:

- **MyOrchestrator** picks *the single next unit of work, right now* —
  short-horizon, mostly deterministic (oldest-first + urgency boosts), one
  optional Engine call only to break a genuine tie. MyPlanner produces a
  *sequence with rationale*, on a rolling basis, not a single pick.
- **MyAdvisor** answers *one posed question* ("should we do X"),
  reactively, when an issue asks it to. MyPlanner runs proactively/on a
  schedule over the whole backlog, not in response to a specific question.

## The single Engine call

Required — same honesty caveat as MyAdvisor: a fixed `NoopEngine` reply
can't produce a meaningful plan, only exercise the plumbing. Unlike
MyAdvisor's original doc (written before a real Engine backend existed),
`ClaudeCLIEngine` shipped and was verified fleet-wide 2026-07-07, so this
is buildable *now*, not blocked on Phase 1 landing.

- **Input:** a deterministically assembled, size-capped context bundle
  (same truncation pattern as MyAdvisor, reused rather than
  reimplemented — see Dependencies): the unbuilt-tools dependency graph
  (MyOrchestrator's own `manifest.json`, not re-derived from doc prose),
  the open core-contract decisions and safety gaps (read from
  MyProjector's synced board if it exists, else the raw org tracking
  issue — see Open questions), and the last N `kind=decision`/`kind=ship`/
  `kind=build` ledger entries fleet-wide (a velocity signal).
- **Output:** `data = {"plan": [{"item": str, "rationale": str, "horizon":
  "next"|"soon"|"later"}, ...], "flags": [str, ...]}`. `flags` surfaces
  things like "pause new tools, close a safety gap first" — a pacing
  judgment, not just a reordered list.
- Against `NoopEngine`: a fixed single-item placeholder plan with no real
  rationale — enough to exercise context-assembly → Engine call → issue
  update → ledger plumbing, **explicitly not a meaningful recommendation**
  (identical honesty caveat to MyAdvisor's doc).

## Deterministic pre-work

1. Read the unbuilt-tools dependency graph from MyOrchestrator's existing
   `manifest.json` (already shipped as part of MyOrchestrator's real
   implementation — reuse it, don't re-derive from `docs/tools/README.md`
   prose a second time).
2. Read open decisions + safety gaps — prefer MyProjector's synced board
   state if that tool exists; else fall back to parsing the org-wide
   tracking issue directly. This fallback is what keeps MyPlanner
   buildable even if MyProjector isn't built first (see Dependencies).
3. Read the last N (default 50) `kind=decision`/`kind=ship`/`kind=build`
   ledger entries across every repo (reuses MyOrchestrator's fleet-wide,
   non-opt-in ledger read — this tool's whole purpose is the fleet view,
   same rationale MyOrchestrator's doc gives for not scoping down).
4. Cap the combined bundle to a fixed size, trimming lowest-relevance items
   first — the same truncation shape as MyAdvisor's pre-work, now the
   sixth tool wanting "shortlist from a corpus, then cite" (MyWiki,
   MySearcher, MyAdvisor, MyDescriber, MyKnowledger were already five per
   README.md's cross-cutting note; strengthens the case for promoting this
   into `my-things-core` rather than leaving it duplicated six times over).
5. Always call the Engine, even on an empty/small backlog (mirrors
   MyAdvisor's step 5) — pacing judgment ("things look calm, no plan
   changes needed") is still a judgment worth recording, not a skip
   condition.

## Ledger

- **Writes:** `kind=plan`, `outcome=success`, `detail`="plan: N items,
  M flags", `data={plan, flags}`.
- **Reads:** fleet-wide `Ledger` + `dev-ledger/` (same non-opt-in scope as
  MyOrchestrator), plus MyOrchestrator's `manifest.json` and (optionally)
  MyProjector's synced board state.

## Guard & Workspace

- No `Workspace`, no PR — it plans, it doesn't build or dispatch, mirroring
  MyOrchestrator's own "recommends, doesn't chain into another tool's CLI"
  stance one level up: MyPlanner recommends a *sequence*, it never invokes
  MyOrchestrator or any build tool directly.
- One side effect: appends/updates a `## Recommended sequence` section on
  the same org-wide tracking issue MyProjector already syncs (not a
  second, competing artifact). Routed through `Policy` as
  `Action(kind="tracking-issue-edit", ...)` — **reusing MyProjector's
  `ASK`-by-default classification for that exact action kind**, not
  inventing a third convention for the same underlying risk (editing
  public issue content unprompted).

## CLI surface

```
myplanner plan [--horizon 4w] [--json]
```

## Test plan

- **Happy path:** fixture manifest + fixture ledger history + fixture
  open-decisions list; assert the Engine is called exactly once (spy
  `Engine`), and a scripted reply's `plan`/`flags` land in both the ledger
  entry and the tracking-issue update.
- **Edge case (empty backlog):** everything shipped, no safety gaps, no
  open decisions; assert the Engine is still called (per pre-work step 5)
  with an explicitly empty-but-present bundle, not skipped.
- Mock `github.Runner` for the tracking-issue edit and MyOrchestrator's
  manifest read; ledger reads exercise real temp fixtures across multiple
  repos (same style as MyOrchestrator's own tests).

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`; reuses MyOrchestrator's
`manifest.json` (hard dependency — MyOrchestrator must exist, which it
already does) and the shared shortlist/truncation helper once that reuse
question (README.md's cross-cutting note) is settled. **Soft**-depends on
MyProjector (degrades to reading the raw tracking issue if MyProjector
doesn't exist yet) — so build order between the two isn't a hard blocker
either direction, but building MyProjector first means MyPlanner's v0
doesn't need its own fallback parser.

**Open questions:**
- **Same manifest-schema question MyOrchestrator's own doc left open**
  ("where does the dependency graph among not-yet-built tools live") is no
  longer open in practice — `manifest.json` shipped — but its *shape*
  (is it expressive enough for MyPlanner's pacing judgment, e.g. "safety
  gap X should block tool Y") hasn't been reviewed against this tool's
  needs. Check before building, extend the schema if not.
- Whether `flags` (e.g. "pause new tools, close a safety gap first")
  should be able to actually influence MyOrchestrator's ranking (a
  boost/penalty signal, same mechanism as its existing `kind=drift`/
  `kind=ask` urgency boosts) or stay purely advisory prose a human reads.
  Leaning toward wiring it in as a ranking signal — that's the whole
  point of having both tools — but that's a change to MyOrchestrator's
  shipped ranking logic, so it's a **confirm-before-implement** core
  change to *that* tool, not something this doc decides unilaterally.
