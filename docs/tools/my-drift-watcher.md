# MyDriftWatcher — design plan

## Purpose

Generalizes the existing `HARNESS.md` drift-check pattern to catch other
cross-repo convention drift (ruff config, pre-commit hooks, CI workflow
shape) across every `My[X]` tool repo, and flags it. Package
`mydriftwatcher`, backlog label `my-drift-watcher`.

## The single Engine call

None — deterministic diffing only, same zero-Engine shape as MyReporter's
default path and MyChangelogger. Drift is either present or absent in a
file's structured content; no judgment is needed to detect it.

## Deterministic pre-work

1. List every repo under the `MyThingsLab` org (`gh repo list`).
2. For each tracked convention file (`pyproject.toml`'s `[tool.ruff]`
   table, `.pre-commit-config.yaml`, `ci.yml`'s job shape), fetch its
   content from each repo (`gh api repos/.../contents/...`, no full clone
   needed since no edits happen).
3. Compare each repo's copy against [`mythings-template`](mythings-template.md)'s
   copy of the same file — resolved from the open question below: the
   dedicated template repo is canonical, not a majority vote across
   whatever tool repos currently exist.
4. Produce a structured diff: `{file, repos_affected: [{repo, diff}]}` per
   tracked file.
5. Compare against this tool's own last `kind=drift` entry for the same
   file+repo pair; skip re-flagging unchanged drift (same dedupe pattern as
   MyReviewer's "don't re-comment identical findings").

## Ledger

- **Writes:** `kind=drift`, `outcome=success` (no drift) or
  `outcome=drift_found`, `detail`="N repos drifted on <file>",
  `data={file, repos_affected, diffs}`.
- **Reads:** its own prior `kind=drift` entries, to dedupe unchanged
  findings across runs (step 5).

## Guard & Workspace

- No `Workspace`, no PR — purely advisory, same stance as MyReviewer: it
  flags, a human or another tool fixes. No tree edits anywhere.
- On drift found, opens a GitHub issue (not a PR) on the affected repo
  describing the diff — `gh issue create` is an `Action(kind="bash", ...)`
  through `Policy`, `ALLOW` by default under MyGuard's rules, same pattern
  as MyGroomer's sub-issue creation.

## CLI surface

```
mydriftwatcher scan [--repos core,my-guard,...] [--file pyproject.toml]
```

## Test plan

- **Happy path:** two fixture repos where one's `pyproject.toml` ruff
  config differs from the other; assert an issue is opened describing the
  specific diff and `kind=drift`/`outcome=drift_found` is written.
- **Edge case (no drift):** both fixture repos identical; assert no issue
  is opened, `outcome=success`.
- Mock `github.Runner` only (both the repo-list and content-fetch calls).

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs a `repo_list` and a
generic `get_file_contents` method — new thin wrappers, same pattern as
existing ones) and on [`mythings-template`](mythings-template.md) existing
(it's the canonical source, not optional). Low urgency while only 2-3
repos exist — drift only matters once there's enough repos to diverge.
Reasonable to build near the end of this batch, once MyScaffolder exists
and is producing new repos regularly (it directly benefits from a fresh
scaffold reliably matching convention, which MyDriftWatcher verifies over
time).

**Open questions:**
- ~~Whether "canonical source" should be a majority vote or a dedicated
  repo?~~ Resolved — see [mythings-template.md](mythings-template.md),
  the same answer MyScaffolder's identical open question settled on.
- Full-clone vs. `contents` API for fetching tracked files: the API avoids
  a clone but is fine-grained (one call per file per repo); assumed
  sufficient for v0 given the tracked file set is small and fixed.
