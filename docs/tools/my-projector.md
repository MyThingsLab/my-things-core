---
tool: MyProjector
repo: my-projector
package: myprojector
status: shipped
added: 2026-07-07
backlog_label: my-projector
engine_call: optional: rewrite this card's last/next-step summary
ledger_kinds: [project-sync]
depends_on: []
---

# MyProjector — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-projector's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-projector/README.md`](../../../my-projector/README.md) and
> [`my-projector/CLAUDE.md`](../../../my-projector/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


**Name tentative** — same status as the `mythings-template` naming question:
nothing is built yet, so renaming costs nothing. `MyProjector` is used below
for concreteness.

## Purpose

Keeps the fleet's GitHub Project board (and any org-wide tracking issue
linked to it, e.g. `fleet-dispatch#1`) in sync with the *live* state of
every repo — reconciling merged/closed PRs and issues into the board's
status fields and a tracking issue's checklist, so the dashboard never
silently drifts from reality. Package `myprojector`, no backlog label of
its own — like MyOrchestrator, it reads other tools'/repos' state rather
than being fed one.

Directly motivated by this session: populating and then correcting
`github.com/orgs/MyThingsLab/projects/1` by hand (18 `gh project item-edit`
calls, a merge-conflict fix, closing an accidentally-created issue, checking
off a tracking issue's boxes) is exactly the mechanical, repeatable
bookkeeping this tool should own.

## The single Engine call

Optional, same shape as MyReporter's `--summarize`.

- **Input:** a card's prior `Last step`/`Next step` text plus the raw
  PR/issue activity for its repo since MyProjector's last run (titles,
  merge/close events, numbers). `context = {"repo": str, "events": [...]}`.
- **Output:** `data = {"last_step": str, "next_step": str}` — rewritten
  one-line prose for the two text fields.
- Against `NoopEngine`: falls back to a deterministic templated string
  (e.g. `"N PRs merged since <ts>: #a, #b, #c"` / `"M open PRs/issues
  remain"`) — mechanical but honest, not full prose. A run with zero
  events skips the Engine call entirely (nothing to summarize).

## Deterministic pre-work

1. List every repo under the `MyThingsLab` org (`gh repo list`, same as
   MyOrchestrator/MyDriftWatcher).
2. For each repo, fetch PR/issue state changed since MyProjector's last
   `kind=project-sync` ledger entry (bookmark window, same pattern as
   MyReporter/MyChangelogger).
3. Read the Project board's current items and field values (needs a new
   `github` capability — see Dependencies).
4. Match each `Tool`-type card to its repo (by title, v0) and compute
   mechanical `Fleet Status` transitions along a fixed lattice: 0 open
   PRs/issues → `Shipped`; ≥1 open → `In Progress`. **Never overrides a
   human-set `Blocked`/`Design Only`** without a `--force` flag — MyGuard's
   "ask before overriding a human decision" spirit, applied to board state.
5. Detect drift: a card whose linked content type changed unexpectedly
   (e.g. a `DraftIssue` card that's now backed by a real `Issue` — this
   *actually happened* to the `my-things-core` card mid-session, cause not
   fully diagnosed, see Open questions). Flag it, don't silently fix it —
   converting a real issue back to a draft is delete-and-recreate, not a
   safe automatic action.
6. Sync a linked tracking issue's checklist: for each checklist line
   carrying an explicit `repo#number` reference, check it off if that
   PR/issue is now merged/closed. **Fuzzy title matching is explicitly out
   of scope for v0** — a checklist line only gets auto-checked if it already
   names the exact PR/issue it tracks; free-text lines stay manual (same
   "prose isn't a schema" caveat MyOrchestrator's own doc flags for its
   dependency graph).

## Ledger

- **Writes:** `kind=project-sync`, `outcome=success|drift_found`,
  `detail`="synced N cards, checked M checklist items", `data={cards_updated,
  checklist_items_checked, drift}`.
- **Reads:** its own last `kind=project-sync` entry (window bookmark, no
  other tool's ledger).

## Guard & Workspace

- No `Workspace`, no PR, no repo checkout — everything is GitHub
  API/GraphQL driven.
- Side effects split into **two risk tiers**, both routed through `Policy`
  but as distinct `Action.kind`s rather than one generic `"bash"` string —
  reinforces the same open question MyGroomer's doc already raised about
  Guard wanting structured `Action.kind`s, now with a second real example:
  - `Action(kind="project-field-edit", ...)` — updating a private board's
    field values. Low stakes (org-members-only board, trivially
    reversible), `ALLOW` by default.
  - `Action(kind="tracking-issue-edit", ...)` / `Action(kind="issue-close",
    ...)` — editing or closing content on a *public* repo. **`ASK` by
    default**, not `ALLOW` — this session's own auto-mode classifier
    correctly blocked an unprompted `gh issue close` on exactly this
    ground ("modifying public content... without the user explicitly
    requesting it"); MyGuard's default ruleset should encode that
    same line, not rely on a human noticing every time.

## CLI surface

```
myprojector sync [--repos owner/a,owner/b] [--dry-run] [--json]
myprojector sync --apply-checklist   # separate flag: the ASK-tier issue-edit path
```

## Test plan

- **Happy path:** fixture project board (3-4 cards) + fixture repo state
  where one card's repo just had its only open PR merged; assert
  `Fleet Status` moves to `Shipped` and `Last step`/`Next step` update
  (with a scripted `NoopEngine` reply).
- **Edge case (drift):** a fixture card whose content type doesn't match
  what MyProjector last recorded; assert `outcome=drift_found` and no
  mutating call is made against it.
- **Edge case (human-set Blocked not overridden):** a card manually set to
  `Blocked` with 0 open PRs; assert it stays `Blocked` without `--force`.
- Mock `github.Runner`/GraphQL client only; no filesystem/git boundary
  needed since nothing touches a working tree.

## Dependencies & build order

Needs a genuinely new core capability: `my-things-core` currently wraps the
`gh` CLI's REST-ish surface (issues, PRs, CI status) — GitHub's Projects
(v2) API is GraphQL-only and was hand-rolled this session via raw `gh api
graphql` calls (confirmed: no `createProjectV2View`/`updateProjectV2View`
mutations exist at all — board **views** genuinely cannot be scripted,
that stays a one-time human setup step, out of scope for this tool
permanently, not just for v0). Proposed: a new `mythings.projects` module
(`ProjectV2` read/write: items, field values, draft-issue creation),
kept separate from `github.GitHub` rather than bolted on, since the
transport (GraphQL vs. `gh` subcommands) genuinely differs — **confirm
before implementing**, same gate as `diff()`/`create_issue()`.

Depends on core `ledger`, `policy`, and the new `mythings.projects` module.
No dependency on any other `My[X]` tool. Soft-depends on a Project board +
at least one linked tracking issue already existing (both do, as of
2026-07-07). See the Cross-cutting note in [README.md](README.md) on how
this tool's role (pure sync, no priority judgment) is bounded against
MyOrchestrator's and MyPlanner's.

**Open questions:**
- **Root cause of the draft→issue auto-conversion** seen this session
  (the very first `gh project item-create` call for a repo-name-matching
  title became a real issue; identical later calls didn't). Step 5's drift
  detection is a safety net, not a fix — worth a minimal repro before
  building, since if it's a real GitHub-side race, every `sync` run's
  own item-creation calls (for new repos) could hit it too.
- Whether `mythings.projects` should support creating brand-new cards at
  all, or only ever sync existing ones — v0 assumption is sync-only
  (new repos still get an initial card by hand), since auto-creation is
  exactly the path that hit the drift bug above.
