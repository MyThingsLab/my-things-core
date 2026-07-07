# MyTester — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-tester's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-tester/README.md`](../../../my-tester/README.md) and
> [`my-tester/CLAUDE.md`](../../../my-tester/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.

**BUILD THIS FIRST.**

## Purpose

Runs pytest with coverage, finds one uncovered unit, and opens a PR adding a
test for it. Package `mytester`, backlog label `my-tester`.

## The single Engine call

Required (this is the tool's reason to exist).

- **Input:** `EngineRequest.prompt` containing the uncovered unit's fully
  qualified name, its source (function/method body via `inspect.getsource`),
  and the surrounding test file's existing style (one sample test, so the
  model matches naming/fixture conventions). `context` carries
  `{"target": "pkg.mod:func", "existing_test_file": "tests/test_mod.py"}`.
- **Output:** `EngineResult.text` is the full contents of one new test
  function (not a whole file — appended under existing imports/fixtures).
  `data` unused.
- Against `NoopEngine`, the reply is a fixed placeholder test body (e.g.
  `def test_noop_placeholder(): assert True`) — enough to exercise the
  read-write-PR path without asserting real coverage gain.

## Deterministic pre-work

1. `git worktree` via `isolation.Workspace` from the issue's target ref.
2. Run `pytest --cov=<package> --cov-report=json` inside the worktree,
   capture `coverage.json`.
3. Parse the coverage report; pick the first uncovered **function or method**
   (by file path, then line number) that isn't `__init__`/dunder/private
   (`_name`) and isn't already under a `# pragma: no cover`.
4. Locate (or decide to create) the matching test file by convention
   (`tests/test_<module>.py`); read one existing test in it for style, or
   fall back to a minimal skeleton if the file doesn't exist yet.
5. If no uncovered unit exists, do nothing (ledger `outcome=skipped`, exit 0)
   — this is the tool's only "no-op" branch and it is deterministic, not a
   model judgment.

## Ledger

- **Writes:** `kind=run`, `outcome=success|skipped|failure`, `detail` =
  target unit name or "fully covered", `data={target, coverage_before,
  coverage_after, pr}`.
- **Reads:** nothing — MyTester doesn't need history, each run is
  self-contained (coverage is recomputed fresh).

## Guard & Workspace

- Every `git`/`gh` side effect (`git checkout -b`, `git commit`, `git push`,
  `gh pr create`) is wrapped as a `policy.Action(kind="bash", payload={
  "command": <argv joined>})` and run through `Policy.evaluate` (MyGuard) first.
  A `DENY` aborts the run and logs `outcome=failure`; an `ASK` under
  `in_github_actions()` is treated as `DENY` (unattended = no prompt to answer).
- Opens exactly one PR via `github.GitHub.open_pr`, base = the issue's target
  branch, head = a worktree branch named `my-tester/<issue-number>`. Never
  merges (harness invariant).
- Never touches files outside the one test file it edits/creates.

## CLI surface

```
mytester run --issue <number> [--repo owner/name] [--base main]
mytester run --local-only   # skip PR, print the generated test to stdout (dev loop)
```

## Test plan

- **Happy path:** a fixture package with one covered and one uncovered
  function; `NoopEngine` reply is appended; assert the new test file compiles
  and the ledger gets `outcome=success` with a PR number in `data`.
- **Edge case (fully covered):** fixture package where coverage is 100%;
  assert no worktree/PR is created and ledger gets `outcome=skipped`.
- Mock only `github.Runner` (the `gh` subprocess boundary) and
  `isolation`'s underlying `git` calls stay real against a throwaway temp
  repo (git itself isn't a system boundary worth mocking — it's fast and
  deterministic).

## Dependencies & build order

Depends only on core (`ledger`, `policy`, `engine`, `github`, `isolation`)
and MyGuard for `Policy`. No dependency on other My[X] tools. **Build this
first** — it's the smallest possible full loop (issue → deterministic
pre-work → one Engine call → PR → ledger) and validates the harness pattern
end-to-end before other tools copy it.

**Open questions:**
- Coverage tool choice: `coverage.py`'s JSON report vs. parsing `pytest
  --cov` text output — JSON is more robust, assume `pytest-cov` is a dev-dep
  of the target repo (not of MyTester itself, which stays dependency-free at
  runtime — it shells out to the target repo's own `pytest`).
- What if the target repo has no coverage tooling configured at all? Assumed
  out of scope for v0 — ledger `outcome=failure` with `detail="no coverage
  config found"`.
