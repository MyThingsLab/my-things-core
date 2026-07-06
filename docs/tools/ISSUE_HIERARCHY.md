# Mother / leaf issues — a backlog shape, not a new tool

Not a `My[X]` tool — a convention that changes how [MyGroomer](my-groomer.md)
produces work and how [MyOrchestrator](my-orchestrator.md) picks it up. The
harness's base assumption is "a tool reads **one** unit of work." This
convention adds a second issue *kind* sitting above that unit: a **Mother**
issue that represents work too large for a single session, decomposed into
many **leaf** issues, each small enough to be one tool's one Engine call.

## The two kinds

- **Mother** — labeled `mother`. Represents an epic: "get the whole My[X]
  tool line built," "migrate everything off X." Its body is a live
  checklist of linked leaves (`- [ ] #123`, `- [x] #124`). **It stays open
  across many sessions** — it is not itself a unit of work any tool
  executes; it's tracked, incrementally decomposed, and eventually closed
  once every leaf under it is done and nothing more remains to spawn.
- **Leaf** — labeled `leaf`, plus whatever backlog label its target tool
  already consumes (`my-tester`, `my-reviewer`, etc. — unchanged). Its body
  references `Part of #<mother>`. Scoped deliberately small: one tool, one
  Engine call, one session. Once real `Engine` backends exist (per
  `ARCHITECTURE.md`'s "cheapest-capable-first"), a leaf additionally
  carries an `engine:cheap` label — the hint that its one Engine call
  should route to the smallest capable backend, since a leaf's whole point
  is being cheap and disposable. A Mother's own decomposition judgment (see
  below) has no such hint — deciding how to split a large epic is a more
  consequential call than executing one leaf.

## Lifecycle (owned by MyGroomer)

MyGroomer already reads the raw backlog and already has a "split
candidate" heuristic (an oversized issue, or one with multiple `## `
headers). This convention turns that one-shot split into a recurring
lifecycle MyGroomer revisits every run:

1. **Fresh raw issue, split candidate:** relabel it `mother` instead of
   closing/replacing it, then spawn an initial **bounded batch** of leaves
   (a fixed cap, e.g. 3–5) — not all conceivable leaves at once. This keeps
   any one moment's open work small and matches "closed over many
   sessions": the Mother is deliberately left with more to decompose later.
2. **Existing open Mother, current leaf batch not yet all closed:**
   nothing to do this run — MyGroomer skips it (`outcome=skipped`,
   deterministic, no Engine call) until the batch clears.
3. **Existing open Mother, current batch all closed, more content
   remains:** spawn the next bounded batch (same Engine call shape as step
   1, reused — "split/label this issue" now applied to "what's left of
   this Mother," not just the original raw body).
4. **Existing open Mother, current batch all closed, nothing left to
   decompose:** close it. **Deterministic, no Engine call** — this is a
   checklist check (every linked leaf closed, no further split content
   flagged), not a judgment.

Steps 2 and 4 need no model call at all; only steps 1 and 3 spend
MyGroomer's Engine call, and both reuse the exact call already designed
("split/label this issue") — nothing new is added to MyGroomer's Engine
contract, only its pre-work grows two more deterministic branches.

## What changes in MyGroomer's own doc

See [my-groomer.md](my-groomer.md)'s updated pre-work and ledger sections.
Summary: `outcome` grows two values (`spawned_leaves`, `closed_mother`)
alongside the existing `labeled`/`split`/`success`; closing a Mother is a
new `Action` (`gh issue close`) through the same `Policy` path as every
other side effect.

## What changes in MyOrchestrator's candidate set

An open Mother due for step 1/3/4 above **is itself a valid candidate** —
just one MyGroomer acts on, not the tool the Mother's content will
eventually need. MyOrchestrator's ranking should also prefer **continuing
an already-started Mother's leaves** over starting a brand-new Mother, the
same instinct that motivated bounded batches above: finish what's open
before spreading into a new epic. See
[my-orchestrator.md](my-orchestrator.md)'s updated pre-work.

## Open questions

- **Batch size isn't fixed here.** 3–5 is a starting guess; the right
  number probably depends on how expensive a leaf's Engine call turns out
  to be once real backends exist. Not decided — a config knob, not a
  constant, once implemented.
- **What counts as "nothing left to decompose"** (step 4) needs a concrete
  check — e.g. re-running the same oversized/multi-header heuristic against
  whatever of the Mother's original body hasn't yet been carved into a
  leaf. Left to MyGroomer's implementation to make concrete.
- **`engine:cheap` is aspirational** — there's no real `Engine` backend to
  route on yet (Phase 0 is `NoopEngine` only). The label is designed now so
  leaves created today are already tagged correctly once Phase 1 lands,
  rather than needing every existing leaf relabeled retroactively.
