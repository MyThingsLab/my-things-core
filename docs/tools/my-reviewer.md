# MyReviewer — design plan

## Purpose

Comments findings on an open PR after checking its diff for correctness
bugs. Package `myreviewer`, backlog label `my-reviewer`.

## The single Engine call

Required.

- **Input:** `EngineRequest.prompt` = the PR's unified diff (or, if it
  exceeds a size cap, the diff restricted to files MySearcher would rank
  highest by touched-identifier density — the size cap is deterministic
  pre-work, not a model decision). `context = {"pr": number, "files":
  [path, ...]}`.
- **Output:** `EngineResult.text` unused; `data = {"findings": [{"file",
  "line", "summary"}, ...]}` — a structured list, empty if none.
- Against `NoopEngine`: `data` absent → treated as `findings=[]`, so
  MyReviewer posts nothing and logs `outcome=skipped` (clean pass-through,
  not a false "found nothing" comment).

## Deterministic pre-work

1. Fetch the PR's diff via `gh pr diff <number>` (a `github.GitHub` method
   this tool adds, mirroring `pr_status`'s pattern of one thin wrapper call).
2. Skip entirely (ledger `outcome=skipped`) if the PR is a draft, or if its
   only changed paths match `paths-ignore` conventions (`**.md`,
   `dev-ledger/**`) — mirrors the CI hardening rule so MyReviewer doesn't
   waste an Engine call on docs-only PRs.
3. If the diff exceeds a line-count cap (default 800), truncate to the
   files with the most changed lines (deterministic, not model-chosen) and
   note the truncation in the prompt's `context`.
4. Check `pr_status()` — if CI already reports `FAILURE`, still proceed
   (a correctness bug and a CI failure are independent signals) but include
   the CI status in `data` for the ledger.

## Ledger

- **Writes:** `kind=review`, `outcome=success|skipped`, `detail`="N
  finding(s) on PR #M" or "skipped: draft/docs-only", `data={pr,
  findings_count, ci_status}`.
- **Reads:** its own prior `kind=review` entries for the same PR number, to
  avoid re-commenting identical findings on an unchanged diff (dedupe by
  comparing the new `findings` list to the last recorded one before
  posting) — this is the one place MyReviewer reads its own history.

## Guard & Workspace

- No `Workspace` — MyReviewer never edits a tree, only reads a diff via API
  and posts a comment. No PR is opened by MyReviewer (it comments on
  someone else's).
- The `gh pr comment` call is an `Action(kind="bash", ...)` through
  `Policy`; MyGuard's defaults don't block comments, but a repo could add a
  rule capping comment frequency per PR if this proves noisy.
- Never approves or requests changes on the PR — commenting only, per the
  harness's "never merge, never gate" invariant extended here to "never
  block": MyReviewer is advisory, matching the advisory/enforcing split in
  `CONVENTIONS.md` (findings are markdown; a human decides what's blocking).

## CLI surface

```
myreviewer check --pr <number> [--repo owner/name] [--max-diff-lines 800]
```

## Test plan

- **Happy path:** a fixture diff with an obviously wrong line (scripted via
  a `NoopEngine` subclass returning one finding); assert the PR comment body
  contains the file/line/summary and ledger `outcome=success` with
  `findings_count=1`.
- **Edge case (draft PR):** `gh pr view` fixture returns `isDraft: true`;
  assert no Engine call is made (verify via a spy `Engine`) and
  `outcome=skipped`.
- Mock `github.Runner` only; the dedupe-against-history check reads a real
  temp `Ledger` file.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs a new `diff(pr:
int)` method — extend `github.GitHub`, don't re-wrap `gh` elsewhere).
Optionally reuses MySearcher's ranking logic for the diff-truncation step
(step 3) rather than reimplementing "most relevant files" — if MySearcher
ships first, import its scoring function; otherwise MyReviewer's truncation
falls back to raw changed-line-count ordering, which is a strict subset of
MySearcher's approach. Build after MyTester and MySearcher.

**Open questions:**
- Extending `github.GitHub` with `diff()` is a change to a shared core
  contract, not just a new tool — per the CLAUDE.md architectural-change
  rule, this should be flagged and confirmed before implementation, not
  silently added.
- Whether `findings` with no `line` (file-level comments) are worth
  supporting in v0 — assumed yes, `line=None` renders as a top-of-file
  comment.
