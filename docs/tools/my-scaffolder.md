# MyScaffolder — design plan

## Purpose

Bootstraps a brand-new `My[X]` tool repo from a proposal — copies the
scaffold, fills the four `CLAUDE.md` seams, vendors `HARNESS.md`. Automates
[`CONVENTIONS.md`](../CONVENTIONS.md)'s "Starting a new tool" checklist.
Package `myscaffolder`, backlog label `new-tool` (consumed from a
workspace-level tracking issue, not a target repo — there is no target repo
yet).

## The single Engine call

Required, but narrow: "expand a free-form tool proposal into the four
`CLAUDE.template.md` seam fields (purpose, Engine call, invariants, backlog
label)."

- **Input:** the proposal issue's title + body verbatim.
- **Output:** `data = {"purpose": str, "engine_call": str, "invariants":
  str, "backlog_label": str}` — one string per template placeholder.
- Against `NoopEngine`: falls back to copying the raw issue body into every
  placeholder verbatim — crude, but the plumbing (scaffold → repo → commit)
  is still fully exercised and testable.

## Deterministic pre-work

1. Read the one un-scaffolded proposal issue (label `new-tool`) from the
   workspace's tracking repo.
2. Derive the repo/package name from the issue title; check it doesn't
   already exist under the `MyThingsLab` org (`gh repo list MyThingsLab`) —
   abort on collision.
3. Copy scaffold files byte-for-byte from the dedicated
   [`mythings-template`](mythings-template.md) repo (`pyproject.toml`,
   `ci.yml`, `.gitignore`, `LICENSE`, `.pre-commit-config.yaml`,
   `dev-ledger/`, `HARNESS.md`, `tests/test_harness_drift.py`) — resolved
   from the open question below: a dedicated template repo, not an
   existing tool, so nothing tool-specific gets copied by accident.
4. Fill `CLAUDE.template.md` (already present in the template's contents)
   with the four seams from the Engine call above and write it as the new
   repo's `CLAUDE.md`.

## Ledger

- **Writes:** `kind=scaffold`, `outcome=success|failure`, `detail`=
  "scaffolded my-<x>", `data={repo_url, issue, seams}`.
- **Reads:** nothing — each scaffold is independent; collision-checking
  (step 2) queries live GitHub state, not the ledger.

## Guard & Workspace

- **Does not use `isolation.Workspace`** — that contract assumes an
  *existing* repo and a `base_ref` to branch from; a brand-new repo has
  neither. MyScaffolder builds the scaffold in a plain temp directory,
  `git init`s it locally, and pushes directly. Flagged as a gap: if a
  second tool ever needs "create a repo from scratch," this local-init path
  should move into `isolation` as a real second contract method rather than
  staying ad hoc inside MyScaffolder — not decided here.
- **The one narrow exception to "PR, never a direct push":** a brand-new
  repo's first commit has no base to PR against. MyScaffolder pushes the
  scaffold directly to the new repo's `main` once, then stops — it never
  pushes to an existing repo's `main` directly, and every subsequent change
  to that repo (by any tool) follows the normal PR-only rule.
- `gh repo create` is a new `Action` kind (`"repo-create"`) not covered by
  MyGuard's default rules (which only pattern-match `bash` commands) — a
  repo wanting to gate *which* proposals get scaffolded would need a new
  MyGuard rule on this kind. Branch protection setup (required checks,
  no-force-push) is a `gh api` config call — a CI/config change, explicitly
  **out of scope for v0**; left as a manual step after scaffolding, flagged
  here rather than silently automated.

## CLI surface

```
myscaffolder new --issue <number>
myscaffolder new --name my-x --purpose "..." --engine-call "..." --label my-x
```
The second form skips issue-reading for interactive/manual use.

## Test plan

- **Happy path:** a fixture proposal issue with a clear name/purpose;
  `NoopEngine` fallback fills seams from the raw body; assert the local
  scaffold directory has `CLAUDE.md`/`HARNESS.md`/`pyproject.toml` etc., and
  a fake `gh`/`git` runner records exactly one `repo create` + one initial
  push, in that order.
- **Edge case (name collision):** `gh repo list` fixture already contains
  the proposed name; assert the run aborts before any local scaffold is
  built or pushed, `outcome=failure`.
- Mock `github.Runner` and the local `git`/`gh` calls; never mock the
  template-filling logic itself.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs `repo_create`, not yet
present — new thin method, same pattern as existing ones) and on
[`mythings-template`](mythings-template.md) already existing (create that
repo first — it's a one-time, not-harness-built piece of infrastructure,
not a `My[X]` tool with its own build-order slot). Meta relative to the
other tools — it doesn't help until there's a backlog of new tool
proposals, so it pays off only after several more `My[X]` tools are queued.
Reasonable to build once 2-3 more tools are planned rather than first.

**Open questions:**
- ~~Should the reference scaffold be copied from an existing tool or a
  dedicated template repo?~~ Resolved — see
  [mythings-template.md](mythings-template.md); MyScaffolder depends on
  that repo existing before it can be built.
- `isolation.Workspace` not covering "create from scratch" is a real gap
  in the core contract, not just this tool's problem — worth a deliberate
  decision before implementation, per the workspace's architectural-change
  rule.
