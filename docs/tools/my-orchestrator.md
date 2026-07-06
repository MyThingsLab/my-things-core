# MyOrchestrator — design plan

**Build this first**, ahead of MyTester. Every other tool in this batch
assumes GitHub Actions' `schedule:`/event triggers are "the conductor"
(per [`ARCHITECTURE.md`](../ARCHITECTURE.md)) — but that's only true once a
real `Engine` backend exists and CI can actually run judgment steps
unattended. Until then, the only worker capable of the judgment step is
the single interactive Claude session — this doc, this conversation. That
makes "which of 15 designed tools / N open issues should the one available
worker tackle next" a real, recurring, currently-manual decision.
MyOrchestrator automates it.

## Purpose

Reads every backlog across the fleet — open issues per repo, and
not-yet-scaffolded tools from this very docs directory — and produces the
single next unit of work for the one available worker, prioritized
deterministically wherever possible. Package `myorchestrator`, no backlog
label of its own (it *is* the thing that reads every other tool's label).

## The single Engine call

Optional, and narrow by design: "given N deterministically-tied top
candidates, choose which the single available worker should tackle next,
and say why."

- Most runs never reach this — see step 4 of the pre-work. It only fires
  when deterministic ranking produces a genuine tie among top candidates
  (same age, same urgency signals, no dependency ordering between them).
- **Input:** the tied candidates' summaries (repo, tool, title, age,
  urgency flags). `context = {"tie_count": k}`.
- **Output:** `data = {"chosen": candidate_id, "reason": str}`.
- Against `NoopEngine`: falls back to the deterministic tie-break already
  computed (strict oldest-first) — same honest-degrade shape as every
  other tool in this batch; a passing plumbing test never depends on this
  call actually resolving ties well.

## Deterministic pre-work

1. List every repo under the `MyThingsLab` org.
2. For each existing tool repo, list open issues carrying that tool's own
   backlog label (per its design doc), **plus every open `mother`-labeled
   issue** (see [ISSUE_HIERARCHY.md](ISSUE_HIERARCHY.md)) due for a
   MyGroomer pass — a mother whose current leaf batch is fully closed
   (either to spawn its next batch or to be closed outright). A mother
   candidate's target tool is always MyGroomer, never the tool its
   eventual leaves will need. For proposal-only "tools" with no repo yet
   (checked against `gh repo list` — same collision check MyScaffolder's
   pre-work already does), the candidate *is* "scaffold this tool," sourced
   from this directory's table in [README.md](README.md) rather than a
   live issue.
3. Filter to **ready** candidates only: a not-yet-built tool is ready only
   if every dependency listed in its own doc's "Dependencies & build order"
   section is already satisfied (a core-contract addition landed, a
   depended-on tool already built) — this is a deterministic graph check,
   not a judgment call.
4. Rank ready candidates: oldest-first as the base rule (same as
   MyGroomer's "process oldest-first"), boosted by live urgency signals
   read from each repo's ledger — an unresolved `kind=drift`/
   `outcome=drift_found`, or a `kind=ask` (MyTelegramBot) still awaiting a
   reply, jump the queue. **A leaf belonging to an already-open mother
   outranks starting a brand-new mother of the same age** — the same
   "finish what's open before spreading into a new epic" instinct
   MyGroomer's own pre-work now applies. If ranking produces a single top
   candidate (the common case), skip the Engine call entirely and report
   it directly.
5. Only on a genuine tie among top candidates does the Engine call (above)
   fire.

## Ledger

- **Writes:** `kind=orchestrate`, `outcome=success`, `detail`="next: <tool
  or repo#issue>", `data={candidates, chosen, reason}`.
- **Reads:** every configured repo's `Ledger` + `dev-ledger/` (fleet-wide
  by default, not opt-in `--repos` like MyWiki/MyReporter — its entire
  purpose is the fleet view, so scoping it down would defeat the point).

## Guard & Workspace

- No `Workspace`, no PR — it decides, it doesn't build. Its one side
  effect is updating a single pinned "next up" tracking issue (`gh issue
  edit`) so the current recommendation is visible without re-running the
  CLI, through the usual `Action(kind="bash", ...)` → `Policy` path,
  `ALLOW` by default.
- **Deliberately does not invoke another tool's CLI directly.** Chaining
  MyOrchestrator's decision straight into, say, `mytester run` in the same
  process would blur the harness's "one unit of work per run" boundary the
  same way was already flagged and rejected for MyDescriber. MyOrchestrator
  recommends; the worker (human or, later, a scheduled Action) acts on it
  as a separate run.

## CLI surface

```
myorchestrator next [--json]
```

## Test plan

- **Happy path:** fixture state with three repos' issues plus one
  not-yet-built tool whose dependencies are all satisfied; assert the
  oldest/most-urgent candidate is chosen without an Engine call (spy
  `Engine` sees zero invocations) and `kind=orchestrate`/`outcome=success`
  is written with the right `chosen`.
- **Edge case (genuine tie):** two candidates with identical age and no
  urgency signals; assert the Engine *is* called exactly once, and its
  reply's `chosen` value is what gets reported — verifying the tie-break
  path is real, not silently skipped.
- Mock `github.Runner` for repo/issue listing; ledger reads exercise real
  temp fixtures across multiple repos.

## Dependencies & build order

Depends only on core `ledger`, `github`, `policy` — **no dependency on any
other `My[X]` tool**, unlike everything else in this batch. This is exactly
why it jumps the queue: it's buildable immediately, and every other tool's
build order (MyTester first, etc.) is itself the kind of decision
MyOrchestrator should eventually be making. Building it first means the
rest of this batch gets built in an order the tool itself would recommend,
rather than one decided ad hoc in conversation.

**Open questions:**
- ~~Where does the dependency graph among not-yet-built tools live?~~
  Resolved in the first real build: a dependency-free `manifest.json`
  (not `.yaml`), shipped inside the `my-orchestrator` repo initially. Its
  canonical copy should move to `docs/tools/` so it sits next to the docs
  it describes and other tools (MyGroomer's readiness checks, if it ever
  needs them) can read the same file instead of a private copy — not yet
  done, flagged for a follow-up.
- **Mother candidates need a signal for "current batch fully closed."**
  Step 2's mother enumeration has to check each open mother's linked
  leaves' state — either by parsing its checklist body (fragile, prose)
  or a structured field MyGroomer writes into its own ledger entries that
  MyOrchestrator can read instead of scraping GitHub issue bodies. Leaning
  toward the latter (ledger `data` is already structured), not decided.
- **This is the first tool whose default scope is the whole fleet**, not
  one repo — worth confirming that's actually wanted (vs. an
  explicit `--repos` flag like MyWiki/MyReporter) before building, since it
  changes what "unattended" means for this tool specifically (it needs
  read access across every repo under the org, not just its own).
- Whether "next up" should be a single pinned issue in `mythings-core`, or
  a dedicated ops-only repo — a smaller version of the
  single-repo-vs-monorepo question already settled for tools in general,
  but this tool isn't really a tool, so the same answer may not apply.
