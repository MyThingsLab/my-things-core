---
tool: MyPipeline
repo: my-pipeline
package: mypipeline
status: designed
added: 2026-07-18
backlog_label: my-pipeline
engine_call: optional: choose among multiple workflow steps whose on matches the same event
ledger_kinds: [handoff]
depends_on: []
---

# MyPipeline — design plan

## Purpose

Declares the fleet's **tool-to-tool handoffs** as data and drives them
automatically, instead of every producer tool hand-coding its own. Today
`my-archivist` files a `my-bibliography`-labeled issue for every new ISBN it
catalogs (`archivist.py:208-232`) — correct, but bespoke: the dependency
("archivist output feeds bibliography") lives only in that one function's
code, nowhere declared, and every future handoff repeats the same
gate/dedupe/file/label/ledger dance by hand.

MyPipeline reads a small declarative **workflow DAG** — "when tool A records
outcome X, file a labeled issue for tool B, built from A's own data" — off the
shared runtime `Ledger`, and files the handoff. It never runs another tool's
code and never imports another tool's package; a handoff is a labeled issue,
exactly like today, just declared once instead of duplicated per producer.
Package `mypipeline`, backlog label `my-pipeline`.

Distinct from **MyOrchestrator** (picks *what to build next* across the
fleet) and **MyConductor** (orders *already-open PRs* into a merge sequence).
MyPipeline is the third axis: *what happens automatically once a step
finishes* — the handoff axis, not the pick axis or the merge axis.

## The single Engine call

**Optional — none in v0.** A workflow step's `on` match and its
`title_template`/`body_template` substitution are both deterministic (plain
`str.format`-style fills against the producer's own `LedgerEntry.data`), the
same shape `my-archivist`'s existing handoff code already is by hand. No
judgment is needed to fill a template from structured fields.

The seam exists for later, mirroring MyGuard's own optional judge
(`Guard(engine=...)`, fired only when no deterministic rule matches): if two
workflow steps both match the same ledger entry, v0 fires **both** (whichever
templates fill successfully) rather than guessing which one is "the" intended
handoff — an Engine call to choose between them is a natural v1 addition once
a real multi-match case shows up, not before.

## Deterministic pre-work

1. Load the workflow DAG — a `workflows.json` list living in `mypipeline`'s
   own package data (see "Where the DAG lives" below), each entry:
   ```json
   {
     "id": "catalog-to-bibliography",
     "on": {"tool": "myarchivist", "kind": "catalog", "outcome": "success"},
     "require_fields": ["isbn"],
     "then": {
       "repo": "my-bibliography",
       "label": "my-bibliography",
       "title": "bibliography: catalog isbn:{isbn}",
       "body": "isbn:{isbn}\n\nCataloged from `{title}` by {author}."
     }
   }
   ```
2. For every repo under `repo_root` with a `.mythings/ledger.jsonl` (same
   convention `myorchestrator.sources.scan_urgency` already relies on): read
   entries newer than MyPipeline's own bookmark for that repo (its own last
   `kind=handoff` entry recording that source, mirroring MyChangelogger's
   own-last-entry incremental window).
3. For each new entry, find every workflow step whose `on` matches
   `(tool, kind, outcome)`. Skip a step if any `require_fields` key is
   missing/empty from the entry's `data` — fail loud (`outcome=skipped`,
   `detail="missing field: isbn"`), never guess a value.
4. Fill `title`/`body` from `entry.data`; dedupe against already-open issues
   in the target repo carrying the target label, matching by title (the exact
   convention `my-archivist._open_bibliography_titles()` and `my-notes`'s
   `file_note` already use) — a re-scanned entry never double-files.
5. File the issue (`mythings.github.GitHub.create_issue` + `add_labels`,
   creating the label idempotently if the target repo doesn't have it yet,
   mirroring `my-notes`'s `_ensure_note_label` retry-once pattern), gated
   through `Policy` (`Action(kind="issue-create", ...)` — MyGuard's routine
   kinds already allow this, see myguard#12/#15).

## Ledger

- **Writes:** `kind=handoff`, `outcome=success|skipped|failure`,
  `detail`="`<workflow id>` -> `<target repo>`#`<issue>`" (or the skip
  reason), `data={workflow_id, source_repo, source_kind, target_repo,
  issue}` — one entry per fired (or skipped) step, written to the **source**
  repo's `.mythings/ledger.jsonl` (that's whose bookmark it advances).
- **Reads:** every scanned repo's `.mythings/ledger.jsonl` (cross-repo, like
  `scan_urgency`); no dev-ledger reads.

## Guard & Workspace

- No `Workspace` worktree needed — MyPipeline only calls `gh issue create`/
  `gh issue edit` via `mythings.github.GitHub`, no git checkout, no PR.
- Every issue-create goes through `Policy.evaluate(Action(kind="issue-create",
  ...))` — routine and ALLOWed by default per myguard#12's fix, but still
  gated, not bypassed, so a locked-down runner (`Guard(default=Decision.DENY)`)
  can still refuse it.
- Never merges, never opens a PR, never edits another repo's code — the
  entire side-effect surface is "file one labeled issue."

## CLI surface

```
mypipeline sync --repo-root <path> --org MyThingsLab [--workflows path/to/workflows.json]
```

One subcommand. No `--engine` flag in v0 (nothing to judge yet, per above).

## Test plan

- **Happy path:** a fixture repo's ledger gets a `kind=catalog,
  outcome=success, data={isbn: "..."}"` entry; assert a labeled issue is
  filed in the target fixture repo with the template substituted correctly,
  and a `kind=handoff, outcome=success` entry is recorded.
- **Missing required field:** the same entry without `isbn`; assert the step
  is skipped (`outcome=skipped`, no issue filed) rather than filing a
  half-templated title.
- **Dedupe edge:** an already-open target-repo issue with the exact templated
  title; assert no second issue is filed, and the entry still advances the
  bookmark (mirrors `my-archivist`'s own dedupe-then-still-count convention).
- **Bookmark edge:** running `sync` twice with no new entries between runs
  must not re-file anything — the second run's candidate set is empty.
- **Multi-match edge:** two workflow steps both matching the same entry;
  assert both fire independently (v0's documented "no arbitration" behavior).
- Mock the `gh` boundary (`FakeGh`); real per-repo `.mythings/ledger.jsonl`
  files via `mythings.testing`'s `Ledger`/`LedgerEntry`, no network.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy` only — no unbuilt tool required.
Most valuable once ≥2 tools have a real producer/consumer relationship, which
already exists today (`my-archivist` → `my-bibliography`); that pair is the
natural first `workflows.json` entry and the reference case to migrate off
`my-archivist`'s own hand-written handoff once MyPipeline ships (a follow-up
PR in `my-archivist`, not part of this build — `_file_bibliography_issues`
keeps working standalone in the meantime, MyPipeline is additive).

**Where the DAG lives:** `workflows.json` ships as `mypipeline` package data,
**not** a core seam — MyPipeline is the only reader/writer at v0. Promote it
into `my-things-core` (mirroring `tools_manifest.json`'s "canonical registry"
shape) only once a second consumer needs to read the declared DAG — e.g.
MyGuide surfacing "what happens after X" to a non-technical user, or
MyDashboard rendering the handoff graph. Don't build that speculatively here.

**Open questions:**

- **Multi-match arbitration.** v0 fires every matching step with no
  judgment. If a real workflow ever needs "pick exactly one," that's the
  Engine seam described above — build it when a concrete case demands it,
  not speculatively.
- **Failure handling for a target repo with no matching label/repo at all**
  (a typo in `workflows.json`, or the target repo doesn't exist). v0 should
  fail loud (`outcome=failure`) rather than silently drop the handoff —
  exact retry/escalation shape (a `needs_human` label, mirroring
  `my-tester green`'s cap-then-escalate convention) is a build-time decision,
  not a design blocker.
- **Cross-repo bookmark placement.** Writing the `handoff` ledger entry to
  the *source* repo (so its own bookmark advances) means a repo MyPipeline
  has scanned but that later goes uncloned would silently stop advancing —
  same limitation `scan_urgency`/`myorchestrator.plans.sync_plans` already
  accept for a partial local checkout. Acceptable now; revisit if the fleet
  ever runs MyPipeline against a partial `repo_root` regularly.
