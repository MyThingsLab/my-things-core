---
tool: MyDescriber
repo: my-describer
package: mydescriber
status: designed
added: 2026-07-05
backlog_label: my-describer
engine_call: write a PR title + description for this diff
ledger_kinds: [describe]
depends_on: [core:diff, tool:my-reviewer, tool:my-wiki]
---

# MyDescriber — design plan

## Purpose

Writes or improves a PR's title and description — grounded in the diff, the
linked issue, and directly relevant ledger history — so every PR-opening
tool can stay simple (open with a minimal deterministic body: issue link +
checklist) and let one dedicated tool produce a good, consistent
description afterward. Package `mydescriber`, backlog label `my-describer`.

## The single Engine call

Required: "write a PR title + description for this diff, given the linked
issue and directly relevant ledger history."

- **Input:** the PR's diff (via `github.GitHub.diff()` — see dependencies),
  the linked issue's title/body (parsed from the PR body's `Closes #N` /
  `Part of #N` reference), and a small ledger-excerpts bundle (reuse of
  MyWiki's shortlist logic — third tool to want this, see the
  cross-cutting reuse note in [README.md](README.md)).
- **Output:** `data = {"title": str, "body": str}`. `body` mirrors the
  `## Summary` / `## Test plan` shape already used for this workspace's own
  PRs — a "why" grounded in the issue + ledger context, and a "what
  changed" summary grounded in the diff.
- Against `NoopEngine`: falls back to a plain, honest, ungenerated body —
  `title` = the linked issue's title, `body` = `Closes #N` plus the raw
  diffstat (file list + insertion/deletion counts). Not curated, but never
  wrong.

## Deterministic pre-work

1. Fetch the target PR's current diff and body (`gh pr view`/`gh pr diff`).
2. Skip if already described and the diff hasn't changed since (dedupe
   against this tool's own last `kind=describe` entry for the PR — same
   shape as MyReviewer's "don't re-comment an unchanged diff").
3. Skip drafts and docs-only PRs — same skip logic as MyReviewer's
   pre-work, for the same reason (don't burn an Engine call on a PR that
   isn't ready or doesn't need curated prose).
4. Parse the linked issue number out of the PR body's `Closes #N` / `Part
   of #N` convention; fetch its title/body.
5. Gather a small ledger-excerpts bundle related to the issue/PR (reuse
   MyWiki's shortlist logic).
6. Cap the combined prompt size — same size-cap pattern used everywhere
   else in this batch (MyReviewer's diff truncation, MySearcher's candidate
   cap, MyAdvisor's context bundle cap).

## Ledger

- **Writes:** `kind=describe`, `outcome=success|skipped`, `detail`="wrote
  description for PR #N", `data={pr, title, diffstat, linked_issue}`.
- **Reads:** its own prior `kind=describe` entries for the same PR, to
  dedupe against an unchanged diff (step 2).

## Guard & Workspace

- No `Workspace` — edits PR *metadata* (title/body) via `gh pr edit`, never
  the tree, and never opens a new PR (it enriches an existing one — the
  first tool in this batch whose job is editing something another tool
  already created).
- `gh pr edit` is an `Action(kind="bash", ...)` through `Policy`; MyGuard's
  defaults allow it (no merge/force-push/destructive pattern).
  **Invariant: MyDescriber only ever changes a PR's title/body, never its
  base or head** — it describes what merges, it never decides what merges.

## CLI surface

```
mydescriber write --pr <number> [--repo owner/name]
```

## Test plan

- **Happy path:** fixture diff + linked issue + ledger excerpts; scripted
  `Engine` reply with a title/body; assert `gh pr edit` is called with
  exactly that title/body and `kind=describe`/`outcome=success` is written.
- **Edge case (draft PR):** assert no Engine call (verify via a spy
  `Engine`) and `outcome=skipped`, same pattern as MyReviewer's draft skip.
- Mock `github.Runner` only.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs `diff()` — the
**second** tool wanting it after MyReviewer, strengthening the case to add
it now rather than defer — and a new `pr_edit()` method). Reuses
MyWiki's shortlist logic (the **third** consumer of that reuse
question, alongside MyAdvisor). Build after MyReviewer (shares `diff()`
and the draft/docs-only skip pattern) and after MyWiki (reuses its
shortlist).

**Open questions:**
- **Chained vs. independent trigger.** Should MyDescriber run automatically
  right after any tool opens a PR, or pick up undescribed open PRs on its
  own cadence/label independently? Recommend independent — chaining two
  tools' Engine calls into one CI job blurs the harness's "one unit of work
  per run" boundary; simpler for MyDescriber to scan for undescribed PRs on
  its own schedule, same as MyReviewer does for unreviewed ones.
- **`github.GitHub.diff()` is now wanted by two tools** (MyReviewer,
  MyDescriber) — worth adding to core now rather than deferring per-tool;
  still flagged as a core-contract change needing confirmation, not decided
  here.
- Whether every PR-opening tool's default body should be reduced to the
  bare minimum (issue link + checklist) now that MyDescriber exists to
  enrich it — a convention change worth applying consistently, noted in
  the cross-cutting section of [README.md](README.md) rather than
  rewriting each tool's doc individually.
