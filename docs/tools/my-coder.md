---
tool: MyCoder
repo: my-coder
package: mycoder
status: shipped
added: 2026-07-05
backlog_label: my-coder
engine_call: one bounded, tools-enabled headless coding session per issue (the fleet's single exception to the tools-disabled Engine call)
ledger_kinds: [code]
depends_on: [core:ledger, core:policy, core:engine, core:github, core:isolation]
---

# MyCoder — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-coder's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-coder/README.md`](../../../my-coder/README.md) and
> [`my-coder/CLAUDE.md`](../../../my-coder/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.

This doc has had exactly one such follow-up edit: the original pre-build plan
described a single tools-*disabled* Engine call that emitted full-file contents,
which is **not** what shipped. The shipped tool runs a full tools-*enabled*
headless session — itself a new Engine-seam pattern, so the rewrite qualifies.
What follows describes the shipped shape; see
[What changed from the pre-build design](#what-changed-from-the-pre-build-design)
for the delta.

## Purpose

The fleet's **"act"** worker. Given one already-picked GitHub issue in a target
repo (a `Candidate` from `my-orchestrator`, dispatched by `fleet-dispatch`),
my-coder closes it as a **draft PR**: it runs a bounded, sandboxed coding
session that reads the repo, makes the smallest change with tests, commits, and
then — as its own single side effect — pushes the branch and opens
`gh pr create --draft`. It never promotes the PR to ready and never merges.

Package `mycoder`. Every prior tool in this line reacts, reviews, tests, or
reports; MyCoder is the first that **writes and commits the change itself**.
Formerly inlined in `fleet-dispatch/fleet_dispatch.py`
(`_prompt_for`/`_dispatch_one`/`_finalize_pr`); now a real, tested, versioned
tool.

## The session seam — the fleet's one exception

MyCoder is the **single deliberate exception** to the fleet's
single-narrow-Engine-call pattern. Every other My[X] tool makes exactly one
tools-*disabled* `ClaudeCLIEngine` call ("judgment only, never a side effect")
and does everything else deterministically. MyCoder's core action cannot be
that shape: closing an arbitrary issue requires an open-ended, multi-turn,
tools-*enabled* headless `claude -p` session — read arbitrary files, edit them,
run the test suite and linter, decide when it is done.

That session is **not** routed through `mythings.engine.Engine`. It is
my-coder's own seam, `session.SessionRunner` (a `Protocol`), with two
implementations:

- **`ClaudeSessionRunner`** — shells out to the `claude` CLI directly via
  `subprocess`, `-p <prompt> --output-format stream-json --verbose`, with a
  real tool allowlist. Bounded three ways: `--max-budget-usd`, `--max-turns`,
  and a wall-clock `timeout`. The `runner` callable is injected so tests never
  shell out to a real CLI. The final `type=result` line of the stream-json
  output settles cost / turn count / final reply / `is_error`; the session is
  `ok` iff the process exited 0, carried no `is_error`, and did not time out.
- **`NoopSessionRunner`** — a dry run that touches nothing, so the mechanical
  path around the session (workspace → commit-count → outcome) can be exercised
  without a model. It always ends `no_changes` (it never commits). This is the
  CLI default.

**Tool allowlist** (ported from my-fleet `fleet_dispatch.DEFAULT_ALLOWED_TOOLS`):
`Read`/`Edit`/`Write`, `Bash(git *)`, the test runner (`pytest`/`python -m
pytest`), the linter (`ruff`), and non-mutating shell inspection (`ls`, `cat`,
`grep`, `printenv`, …). `rm`/`pip`/`find` stay off (they mutate or run code).
**`gh` stays off deliberately** — a session *edits and commits only*; my-coder
itself owns the single push + draft-PR step so that one side effect is the only
thing Policy/Guard has to gate. A `--disallowedTools` deny-list keeps the
session from burning tokens on `.venv`/`__pycache__`/`.git`/`dev-ledger` noise.

**Secret redaction.** A session transcript is persisted and summarised into the
ledger; `session.redact_secrets` runs `mythings._secrets` over the stdout and
replaces anything credential-shaped with `[REDACTED-<name>]` before either the
transcript or the ledger is written. Redaction over rejection keeps the
transcript's forensic value while removing the span.

## The loop (`coder.Coder.run`)

One issue per invocation; iterate by re-invoking, not by looping inside one run
— `fleet_dispatch`'s durable-attempt/retry machinery already covers that layer.

1. **Pick the issue.** `pick_issue(number)` scans `github.list_issues()`; if the
   number is not an open issue → `outcome=skipped`, no session.
2. **Sandbox.** Open a `mythings.isolation.Workspace` git-worktree on
   `origin/<base>` (the live checkout is never touched), `git checkout -B
   mycoder/<repo>-<issue-number>` so every commit the session makes lands on
   that branch, and record the base SHA.
3. **Run the session.** `session_runner.run(prompt, cwd=tree, max_budget_usd,
   max_turns, timeout_s)`. The prompt hands the session the issue title/body and
   the target repo's own `CLAUDE.md`/`HARNESS.md` as authoritative conventions,
   and instructs it to make the smallest change with tests, leave the suite and
   linter green, commit, and **not** run `git push` or any `gh` command.
4. **Redaction alert.** If the session leaked credential-shaped text, write a
   separate `kind=secret_alert` ledger entry recording which patterns were
   redacted (distinct from the tool's own `code` kind).
5. **Classify the outcome:**
   - session not `ok` → `outcome=failure`.
   - zero commits over base → `outcome=no_changes`.
   - `--run-tests` set and the suite fails in the worktree → `outcome=failure`.
   - Policy blocks the PR action (see below) → `outcome=denied`.
   - commits present but `git push` fails → `outcome=needs_review` (work exists
     but no PR could be opened).
   - a real commit **and** an opened draft PR → `outcome=success`.
6. **Open the PR.** Only after the gate passes and the push succeeds:
   `github.open_pr(draft=True, base=<base>, head=<branch>)`. The PR body is
   `Closes #<n>` + a readiness checklist (scope matches / tests green) + the list
   of files touched. Never marked ready, never merged — a human always merges.

The full set of outcomes: **`success` | `needs_review` | `no_changes` |
`skipped` | `denied` | `failure`**.

## Guard & Workspace

The session's own `git` side effects (commits) happen entirely inside the
throwaway `Workspace` worktree. The **one** side effect my-coder performs itself
— the push + `gh pr create --draft` — is wrapped as `Action(kind="bash", …)` and
run through `Policy.evaluate` (MyGuard) first, evaluated `under(unattended=
in_github_actions())`; a non-`ALLOW` decision yields `outcome=denied` with no
PR. MyCoder opens at most **one** PR per issue, as a **draft**, head
`mycoder/<repo>-<issue-number>`, base the repo's default branch, and never
promotes or merges it. It never touches a repo other than the one named by the
issue it was given.

## Ledger

- **Writes:** `kind=code`, `outcome` one of the six above, `detail` a short human
  line ("opened draft PR #M for #N", "session left no commit for #N", the skip/
  failure reason), `data` = `{issue, pr, files_touched, tests_passed, turns,
  cost_usd, pr_url}` as available. A redaction additionally writes one
  `kind=secret_alert` entry.
- **Reads:** none — one issue per run, stateless.

## CLI surface

```
mycoder build --repo <owner/name> --issue <N>
              [--source <path>]            # local checkout of the target repo
              [--base main]
              [--session-runner claude|noop]   # default noop (dry run)
              [--max-budget-usd 5.0]
              [--max-turns 40]
              [--session-timeout-s 1800.0]
              [--run-tests]
              [--ledger <path>]
              [--json]
```

## Dependencies & build order

The first tool to name all **five** core contracts — `ledger`, `policy`,
`engine`, `github`, `isolation`. It calls `ledger`/`policy`/`github`/`isolation`
directly; `engine` is named because MyCoder is defined precisely by *replacing*
the tools-disabled Engine call with its own tools-enabled session seam — the
seam stands in the Engine's structural place. Built out of order (ahead of its
dependency position) because the user asked for it directly as the fleet's
highest-signal readiness test: the first tool whose committed *content* was
generated, not hand-written by the invoking session.

## What changed from the pre-build design

The original plan (branch `docs/my-coder-design`, never merged) described a
**single tools-disabled Engine call** that returned full-file contents
(`data = {"files": {path: content}}`), a required declared file-scope in the
issue body, and a hard scope-filter dropping out-of-scope paths — closely
mirroring MyTester. That never shipped. The blocker was always that "write the
diff for this issue" is the one judgment a fixed `NoopEngine` reply can't stand
in for; rather than route it through `Engine`, the shipped tool runs a full
tools-enabled headless session that discovers its own file scope, edits, and
commits. Consequences of the change:

- **No declared file-scope, no scope-filter.** The session reads and edits
  whatever the issue requires within the one repo's worktree; isolation, not a
  path allowlist, is the boundary.
- **No `NoopEngine` placeholder.** The dry-run seam is `NoopSessionRunner`, which
  never commits and so always ends `no_changes` — it proves the mechanical path,
  not generation quality.
- **Richer outcomes.** `needs_review` (committed but push failed) and `denied`
  (Policy blocked the PR) join `success`/`no_changes`/`skipped`/`failure`.
- **The single Engine-call pattern no longer holds for this tool** — this is the
  documented, deliberate fleet-wide exception.
