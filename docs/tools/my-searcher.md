# MySearcher — design plan

## Purpose

Indexes a repo's files and ranks the ones most relevant to a given issue.
Package `mysearcher`, backlog label `my-searcher`.

## The single Engine call

Required.

- **Input:** `EngineRequest.prompt` = the issue title + body, plus a
  deterministic shortlist of candidate files (already narrowed by the
  pre-work below — the model ranks a shortlist, it does not scan the whole
  tree). `context = {"candidates": [path, ...], "issue_number": N}`.
- **Output:** `EngineResult.text` unused; `data = {"ranked": [path, ...]}`,
  the candidates reordered by relevance (a permutation, not new paths — the
  model may not invent files outside the shortlist).
- Against `NoopEngine`: `data` is absent, so MySearcher falls back to the
  deterministic pre-ranking order unchanged — still a usable (if cruder)
  result.

## Deterministic pre-work

1. Walk the repo tree (respecting `.gitignore` via `git ls-files`), building
   a lightweight index: path, top-level identifiers (function/class names
   via `ast.parse` for `.py`; a plain grep of exported symbols for other
   languages — best-effort, not required to be exhaustive).
2. Tokenize the issue title/body (simple lowercase + split on non-alnum).
3. Score every indexed file by naive term overlap (token intersection count
   between issue tokens and {path components ∪ identifier names}).
4. Take the top N (default 20) by score as the **candidate shortlist** —
   this bounds the Engine prompt size and is the step that makes the tool
   cheap even on a large repo.
5. If N < 2, skip the Engine call entirely (nothing to rank) and return the
   shortlist as-is.

## Ledger

- **Writes:** `kind=search`, `outcome=success|skipped`, `detail`="ranked
  <k> candidates for issue #N", `data={issue, candidates, ranked}`.
- **Reads:** nothing — each search is independent; a future MyGroomer or
  MyCoder could read MySearcher's last `kind=search` entry for an issue
  instead of re-running the index, but that's a caller's choice, not
  MySearcher's.

## Guard & Workspace

- Read-only over the repo tree; no `Workspace` worktree needed if run against
  a plain checkout (no edits are made). If invoked from a bare clone in CI,
  a shallow `git clone`/checkout is the pre-work's job, not `isolation`'s.
- No PR, no push, no comment by default — the ranked result is returned via
  ledger `data` and stdout/JSON. An optional `--comment` flag posts the
  ranked list to the issue, which is the one `Action(kind="bash", ...)`
  routed through `Policy` (same as MyReporter's comment path).

## CLI surface

```
mysearcher rank --issue <number> [--repo owner/name] [--top 20] [--json]
mysearcher rank --issue <number> --comment   # also posts ranked list to the issue
```

## Test plan

- **Happy path:** a fixture repo (3-4 files with distinct identifiers) and
  an issue body mentioning terms unique to one file; assert that file ranks
  first both in the deterministic pre-ranking and (with a scripted
  `NoopEngine` subclass reply) after the Engine reorder.
- **Edge case (no candidates score > 0):** issue body shares no tokens with
  any file; assert the shortlist still returns (fallback: most-recently
  modified files) rather than an empty list, and `outcome=success` (a weak
  ranking is not a failure).
- Mock `github.Runner` for `--comment`; the file index is built against a
  real temp git repo (git ls-files is the boundary, not a stub).

## Dependencies & build order

Depends on core `ledger` and `github` (comment path only). No dependency on
MyGuard beyond the shared `Policy` seam for the comment action. Build after
MyTester; independent of MyReporter. Explicitly designed for reuse by
**MyGroomer** (labeling needs relevant-file context) and **MyCoder** later
(deferred) — see the `graphify` skill's file-relevance graph as a possible
future backend for the pre-work index instead of naive token overlap.

**Open questions:**
- Whether the index (step 1) should be cached across runs (e.g. in
  `dev-ledger/` or a `.mythings/index.json`) rather than rebuilt every
  invocation — deferred until a real repo's walk time is measured;
  assume rebuild-every-time for v0 since it's the simplest correct thing.
- Multi-language identifier extraction beyond Python is best-effort; not
  blocking for v0 since mythings-core repos are all Python.
