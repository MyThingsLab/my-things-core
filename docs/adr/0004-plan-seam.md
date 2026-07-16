# ADR 0004 — the shared "per-repo task DAG" seam

- **Status:** proposed
- **Date:** 2026-07-13
- **Issue:** [my-things-core#117](https://github.com/MyThingsLab/my-things-core/issues/117)

## Context

A Pi-server session compared `MoneyBallingAI/MBAI`'s independent agentic
harness against the fleet's five contracts. MBAI had already solved a problem
the fleet has no model for: a large product repo, organized into internal
layers/subpackages, needs a shared plan that survives across sessions and
machines without live shared state. MBAI's version is `plans/<slug>.md` — a
versioned markdown task DAG, generated once from an epic, deterministically
reconciled from live issue/PR state on every run (no model call), and only
re-planned by a model on demand.

That comparison (`my-things-core#115`) was split into four issues. Two
downstream consumers both need the same task-DAG primitive: `my-orchestrator`
would use it to prefer dependency-ready tasks over oldest-first ranking
(`my-orchestrator#19`); `my-planner` would use it to write a plan from an epic
(`my-planner#12`). Building the format twice, once per consumer, is the same
mistake ADR 0001 and ADR 0002 both name explicitly — the seam comes first.

## Decision

**Promote into core**, as `mythings.plan`: parse/render a markdown task table,
plus the two pure functions consumers actually need — `ready()` (dependency-
gated task selection) and `reconcile()` (deterministic status sync from live
GitHub state, no model call).

**This is a seam, not a sixth load-bearing contract.** `harness.md` names five
(`ledger`, `policy`, `engine`, `github`, `isolation`) and says not to add a
sixth lightly. `mythings.plan` is the same class of thing as `mythings.corpus`
(ADR 0001), `mythings.mastery` (ADR 0002), and `mythings.embed` (ADR 0003):
promoted, focused, optional infrastructure a subset of tools opt into — not a
rule every tool in the fleet must obey.

**The plan file lives in the target repo, not in any fleet tool's own state.**
`plans/<slug>.md` is checked into the repo being built, the same repo whose
issues it tracks. This is also the direct fix for a different problem raised
in the same investigation — a laptop session and a Pi session seeing
different state — since git, not a tool's local ledger or a chat session
transcript, becomes the thing that actually stays in sync.

## The API

```python
PlanTask(title, owner, depends_on=(), issue=None, status="todo")

parse(text)                              -> [PlanTask]
render(tasks)                            -> str
read_plan(path)                          -> [PlanTask]
write_plan(path, tasks)                  -> None
ready(tasks)                             -> [PlanTask]   # non-done, deps all done
reconcile(tasks, *, repo, runner=_gh)     -> ([PlanTask], changed: bool)
```

- A task's `depends_on` entries are **titles**, not a separate id column —
  matching MBAI's own tables, which reference tasks the same way. Titles must
  be unique within one plan file; not enforced with new machinery, just
  documented.
- `ready()` fails closed: a `depends_on` title with no matching task (a typo,
  a dangling edge) is treated as unmet, never silently assumed satisfied.
- `reconcile()` needs no method `github.GitHub` doesn't already have —
  single-issue-state and PR-references-issue lookups don't exist there today,
  so two small helpers (`_issue_state`, `_open_pr_references`) call the
  injected `Runner` directly inside `plan.py`, the same way `projects.py`
  makes its own GraphQL calls rather than growing the `GitHub` class for a
  need only one seam has.

Preserves the same three properties every core module must (ADR 0001, 0002,
0003):

1. **Zero new dependencies.** Pure stdlib (`re`, `json`, `pathlib`).
2. **No import-time side effects.** Nothing touches disk or the network until
   a caller passes an explicit path or calls `reconcile()`.
3. **Inert by default.** No tool reads or writes a plan unless it opts in.

## Known limitation — the PR-reference check is a text search

`_open_pr_references` shells out to `gh pr list --search "<n> in:body"` — a
literal-text search, not GitHub's structured "closing issue" cross-reference
graph. It can false-positive on a PR that merely mentions the issue number in
passing. `reconcile()` also only ever moves a task's status forward (closed
issue → `done`, an open referencing PR → `in_progress`); it never reverts
`in_progress` back to `todo` if that PR closes unmerged. Both mirror MBAI's
own `reconcile_plans`, which has the identical shape, and are acceptable
first-cut behavior. A GraphQL-based precise cross-reference query (the same
pattern `projects.py`'s `_graphql` already uses) is a natural follow-up once a
real consumer (`my-orchestrator#19`) exercises this path and shows it matters
in practice — not built speculatively now.

## Consequences

- `my-orchestrator#19` is built next: reconcile a repo's `plans/*.md` before
  ranking candidates, and exclude a not-yet-`ready()` task's issue from the
  candidate pool even if it's the oldest open issue.
- `my-planner#12` follows or runs in parallel: reuse its existing
  `_ask_engine` machinery, retargeted to write one repo's plan from an epic
  instead of a fleet-wide ranking.
- Nothing existing changes. `mythings.plan` is inert until a consumer opts in.
