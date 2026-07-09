---
tool: MyConductor
repo: my-conductor
package: myconductor
status: designed
added: 2026-07-08
backlog_label: my-conductor
engine_call: order these PRs into a coherent merge story, within the given constraints
ledger_kinds: [conduct]
depends_on: []
---

# MyConductor — design plan

## Purpose

Recommends the **order in which to merge the fleet's open PRs** so the combined
`main`-branch history across repos tells a coherent story — prerequisites first,
related changes grouped, and cross-repo dependencies never violated. Package
`myconductor`, backlog label `my-conductor`.

Distinct from its neighbours:

- **MyOrchestrator** picks the next *issue* to work on; it never looks at PRs.
- **my-planner** orders the *build backlog* (what to build next); MyConductor
  orders *already-open PRs* (what to merge next).
- **MyAdvisor** answers one posed "should we do X" question. MyConductor answers
  a standing one — "in what order do these N open PRs merge?" — recomputed from
  live PR state each run.

It is the tool that would have said "merge `my-things-core#29` before
`my-projector#1`" up front, instead of that surfacing as a red CI.

## The single Engine call

Required: "order these merge-ready PRs into the sequence whose combined history
reads as a coherent story, within the given dependency constraints."

- **Input:** the open-PR list (repo, number, title, body-summary, CI status) plus
  the **deterministically computed dependency DAG** (hard edges) and a size cap.
  `context = {"pr_count": n, "hard_edges": [[from, to], ...]}`.
- **Output:** `data = {"order": [{"repo", "number", "rationale"}], "groups":
  [[pr, ...], ...], "flags": [str, ...]}` — a **permutation of the given PRs**
  (the model may not invent a PR), each with a one-line why; `groups` cluster PRs
  that form one narrative unit.
- **Determinism guardrail:** the returned order is validated as a topological
  linearization of the DAG. An order that would merge a consumer before its
  dependency is **repaired** (stable-sort the model's order under the DAG
  constraints), not trusted blindly — the Engine chooses *among valid* orders and
  writes the narrative; it can never override a real dependency. Same discipline
  as MySearcher's permutation rule and my-researcher's cite-only rule.
- Against `NoopEngine`: no narrative — emits a deterministic topological order
  (Kahn's algorithm, tie-broken by repo then number) with empty rationales. Still
  a correct, mergeable order, just no story.

## Deterministic pre-work

1. Resolve the target repos (org manifest / `gh repo list`) and enumerate open,
   non-draft PRs per repo (`gh pr list --state open`).
2. For each PR gather base/head branch, body, CI rollup (reuse
   `github.pr_status`), and changed files.
3. Build the dependency DAG edges:
   - **Explicit markers** parsed from the body — `Stacked on #N`,
     `Depends on <repo>#N`, `Blocked by …` (the exact phrases we already write by
     hand).
   - **Same-repo stack** — a PR whose base branch is another open PR's head.
   - **Cross-repo import** — a consumer PR that adds a
     `from mythings.<mod> import <Name>` whose `<Name>` is added by an open
     `my-things-core` PR's diff (best-effort; this is the `#29 → my-projector#1`
     edge, detected automatically).
4. Detect cycles → **flag them** and do not ask the Engine to linearize an
   impossible graph (surface as a blocker).
5. Cap the PR set (default 30). If ≤1 mergeable PR, skip the Engine call and
   return it as-is.

## Ledger

- **Writes:** `kind=conduct`, `outcome=success|skipped`, `detail`="ordered `k`
  PRs", `data={prs, order, hard_edges, cycles, comment_url}`.
- **Reads:** nothing — each run recomputes from live PR state; re-running is
  expected as PRs open/merge.

## Guard & Workspace

- **No `Workspace`** — read-only over PRs. One side effect: post the recommended
  order to the org tracking issue (or print / `--json`), an `Action(kind="bash",
  …)` through `Policy`, `ALLOW` by default.
- **Never merges** — advisory only, like MyReviewer/MyAdvisor. It orders and
  narrates; a human runs the merges.

## CLI surface

```
myconductor order [--repos a,b,...] [--tracking owner/repo#N] [--json]
myconductor order --comment   # also posts the order to the tracking issue
```

## Test plan

- **Happy path:** a fixture open-PR set (mocked `gh`) with one explicit
  `Stacked on` edge and one cross-repo import edge; a scripted `Engine` order;
  assert the output honours both hard edges, renders rationales, and writes
  `kind=conduct`/`outcome=success`.
- **Guardrail edge:** the scripted `Engine` returns an order that violates a hard
  edge (consumer before dependency); assert the tool **repairs** it to a valid
  topological order rather than emitting the invalid one.
- **Cycle edge:** two PRs mutually `Depends on` each other; assert the cycle is
  flagged and the Engine is not trusted to linearize it (`skipped`/flag).
- **`NoopEngine`:** assert a valid topological order with empty rationales.
- Mock the `gh` boundary; DAG construction runs against real fixture PR
  bodies/diffs, never mocked.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`. **Third caller of the "order/select
a set with one Engine call + deterministic fallback" shape** (after my-planner
and MyOrchestrator's tie-break) — the ≥3-caller trigger the design docs set for
promoting a shared **ordered-selection helper** into `my-things-core`. Build the
helper first (see cross-cutting note in [README.md](README.md)), then MyConductor
is thin on top of it. Independent of the other unbuilt tools.

**Open questions:**

- Cross-repo import detection is best-effort (regex over added import lines vs. an
  open core PR's added symbols). A miss just means the human still catches it, as
  today; full static resolution is out of scope for v0.
- Whether to also gate on branch-protection / required-review state (a green but
  unreviewed PR shouldn't top the list). v0 orders by dependency + narrative and
  surfaces CI status; review-state gating is a later refinement.
- Should it ever *act* — open a merge queue, label "ready to merge #k"? Deferred;
  advisory only for v0, never merges.
