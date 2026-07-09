---
tool: MyDashboard
repo: my-dashboard
package: mydashboard
status: shipped
added: 2026-07-08
backlog_label: my-dashboard
engine_call: optional: write the two-sentence state-of-the-fleet banner
ledger_kinds: [dashboard_render]
depends_on: []
---

# MyDashboard — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-dashboard's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-dashboard/README.md`](../../../my-dashboard/README.md) and
> [`my-dashboard/CLAUDE.md`](../../../my-dashboard/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


## Purpose

Renders **one org-wide dashboard page** that answers "what is the fleet,
and how is it doing right now?" at a glance, grouping every repo into
three shelves:

- **Development harness** — the tools that run the autonomous cycle
  (my-planner, my-orchestrator, my-tester, my-changelogger, my-projector,
  my-reporter, my-guard, my-todo, my-docs, my-template, my-things-core).
- **Services** — things that stay up and get consumed rather than run to
  completion: my-server (ledger HTTP), my-telegram-bot (notifications /
  ASK relay), the docs site (mythingslab.github.io).
- **Casual development** — the human-facing "make or learn something"
  tools: my-typster, my-presentation, my-researcher, my-uni, my-site,
  my-searcher, my-scraper, my-archivist, my-librarian, my-idea.

Per tool: one-line purpose (from its CLAUDE.md Purpose seam), CI badge,
open issues/PRs count, last dev-ledger entry, last runtime-`Ledger`
activity. Package `mydashboard`, backlog label `my-dashboard`.

Same "keeps a generated surface in sync" family as MyDocs (per-tool
pages) and MyProjector (board/checklist) — this is the *front page* those
two don't render: cross-tool, grouped, status-first.

## The single Engine call

Optional, behind `--summarize` (same opt-in shape as MyReporter): "from
this deterministic status table, write the two-sentence 'state of the
fleet' banner." Default run is **fully deterministic — no Engine call**;
against `NoopEngine` with `--summarize` the banner is omitted, never
fabricated.

## Deterministic pre-work (the whole tool, in the default mode)

1. Enumerate org repos (`gh repo list`), classify into the three shelves
   from a checked-in `shelves.toml` (explicit mapping, not inference —
   a new repo missing from the map renders in an "unshelved" section so
   drift is visible, not silent).
2. Per repo: `gh` for open issue/PR counts + latest CI conclusion on
   main; read `dev-ledger/` tail and the shared `Ledger` tail for
   last-activity lines.
3. Render `dashboard/index.md` (Jekyll page for the docs site) from a
   fixed template — same verbatim-render discipline as MyDocs against
   `NoopEngine`.

## Ledger

- **Writes:** `kind=dashboard_render`, `outcome=success|skipped`,
  `data={repos, stale, pr}`; skipped when the rendered page hashes equal
  to the live one (MyDocs' staleness-hash pattern, zero-diff → no PR).
- **Reads:** every repo's ledgers (read-only) for the activity columns.

## Guard & Workspace

Writes only via a PR to the docs-site repo (`Workspace` clone → branch →
`gh pr create`), routed through `Policy`; **never merges**. Serving the
page live is *not* this tool's job — my-server may later grow a read-only
`/dashboard` route that renders the same data on request (separate issue
in my-server's backlog, not a dependency).

## CLI surface

```
mydashboard render --org MyThingsLab --repo-root <docs-site clone>
                   [--summarize] [--engine noop|claude-cli] [--no-pr]
```

Joins `fleet_cycle.py` after the `mydocs` step once shipped.

## Test plan

- Happy path: mocked `gh` runner + fixture ledgers → assert grouping,
  counts, and that an unmapped repo lands in "unshelved"; PR opens via a
  spy `Policy`.
- Edge: zero-diff re-render → `outcome=skipped`, no Engine call, no PR
  (spy Engine asserts).
- `--summarize` against `NoopEngine` → banner omitted, page still valid.

## Dependencies & build order

Core `ledger`, `github`, `isolation`, optionally `engine`; my-guard for
policy. Reuses MyDocs' staleness-hash + one-PR pattern — build after
reading it, sharing conventions rather than code. Independent of MyIdea.

**Open questions:**

- Should `shelves.toml` live in the dashboard repo (self-contained) or in
  the docs site (next to the rendered page)? Recommend the dashboard repo
  — the tool owns its classification input.
- Whether "services" should show liveness (ping my-server's endpoint) or
  only repo health. Recommend repo health in v0; liveness needs a
  deployment story the fleet doesn't have yet.
