---
tool: MyTodo
repo: my-todo
package: mytodo
status: shipped
added: 2026-07-08
backlog_label: my-todo
engine_call: optional: prioritise issues into Now/Next/Later
ledger_kinds: [todo]
depends_on: []
---

# MyTodo — design plan

> **Historical.** This is the pre-build design plan, frozen as of MyTodo's first
> ship. It is **not** kept in sync with the implementation — for current behavior
> (CLI surface, flags, invariants) read
> [`my-todo/README.md`](../../../my-todo/README.md) and
> [`my-todo/CLAUDE.md`](../../../my-todo/CLAUDE.md) in the tool's own repo. Only
> genuinely cross-tool contracts get a follow-up edit here.

## Purpose

Curate a durable, checked-in `TODO.md` from live signals and open a PR — the
**prospective** counterpart to MyReporter's retrospective digest. Where
MyReporter says *what happened* and MyPlanner posts an ephemeral *recommended
sequence* onto a tracking issue, MyTodo writes a standing "what to do next"
checklist into the tree, grouped **Now / Next / Later**. Package `mytodo`,
backlog label `my-todo`.

Two modes:
- `mytodo repo --repo owner/name` — one repo's own `TODO.md` from its open issues.
- `mytodo org --org <org> --into owner/name` — an org-wide roll-up aggregating
  every repo's open issues into one board (each line prefixed `repo#n`).

## Reads (deterministic pre-work, no model)

1. **Open issues** via `mythings.github.GitHub.list_issues` (per-repo) or a single
   `gh search issues --owner <org>` (org mode). Title, number, labels.
2. **MyPlanner's latest `kind=plan` entry**, read straight from MyPlanner's runtime
   ledger on disk — the *same seam MyOrchestrator uses* (`read_plan`, defaulting to
   `<source>/../my-planner/.mythings/ledger.jsonl`). A `next` horizon surfaces as a
   "Planner focus" note; a "pause new tools" flag becomes a banner. **No package
   dependency on MyPlanner** — coupling is through the ledger file only. Missing
   ledger ⇒ no signal (issues-only), unchanged.

## The single Engine call (optional)

Prioritising the gathered issues into Now / Next / Later
(`prioritize.engine_sections`). Off by default (`--engine noop`): with no engine,
issues are grouped deterministically by label (`safety`/`bug` → Now,
`core-contract`/`needs-decision` → Next, rest → Later). Any empty or unparsable
model reply degrades to that same deterministic grouping — MyTodo never fabricates
items or reorders blindly. Same optional-Engine posture as MyReporter's
`--summarize`.

## Writes / invariants

- Writes exactly one file (`TODO.md`) inside an `isolation.Workspace` and opens
  exactly one PR through `Policy` (default-allow — a single non-destructive doc PR,
  same rationale as MyReporter/MyChangelogger). **Never merges; never mutates
  issues.**
- Idempotent: a re-run with no issue changes produces an identical `TODO.md` and is
  recorded `skipped` — no empty PR. Ledger `kind=todo`.
- Runtime dependency: `my-things-core` only.

## Not in scope (v0)

Per-issue plan-to-issue matching (the plan shapes ordering hints and banners, not
individual issue placement); scheduled/automatic runs (a fleet or cron concern);
closing or editing issues.
