---
tool: MySyndicator
repo: my-syndicator
package: mysyndicator
status: designed
added: 2026-07-08
backlog_label: my-syndicator
engine_call: none — deterministic
ledger_kinds: [syndicate]
depends_on: []
---

# MySyndicator — design plan

## Purpose

Applies **one change to many repos** and opens **one PR per repo** — the
deterministic (no-LLM) cross-repo fan-out the fleet currently lacks. For
mechanical, identical changes: re-vendoring `HARNESS.md`, adding a shared CI
step, a banner, a config bump, a formatter pass. Package `mysyndicator`, backlog
label `my-syndicator`.

Distinct from **fleet-dispatch**, which throws a full Claude worker at each repo —
the right tool when the change needs *judgment* per repo (different code, a
real feature). MySyndicator applies a **fixed transform**, so it's cheap,
reproducible, and reviewable, and it never spends tokens. The line: mechanical
transform → MySyndicator; needs-judgment change → fleet-dispatch.

## The single Engine call

**None — deterministic.** Same as MyReporter/MyChangelogger. The transform is
*specified*, not judged; smuggling per-repo adaptation into it would either need
an Engine call (making it fleet-dispatch) or produce wrong diffs. Keeping it
LLM-free is the whole point — a fan-out you can trust to be identical.

## Deterministic pre-work

1. Resolve the target repo set — an explicit list, or all org repos matching a
   filter (e.g. every `my-*` tool repo, via `gh repo list`).
2. Load the transform spec, one of:
   - **file op** — write/replace a file with given content (e.g. re-vendor
     `HARNESS.md` from `mythings._harness.harness_text()`), or delete it;
   - **patch** — apply a unified diff (`git apply`), **skipping** repos where it
     doesn't apply cleanly (reported, never forced);
   - **command** — run a fixed, allowlisted command in the worktree
     (e.g. `ruff format`).
3. Per repo, in a `Workspace` worktree off the base branch: apply the transform;
   if it's a **no-op** (already applied), skip that repo — **idempotent, no empty
   PR**; run the repo's fast test command; open the PR only if tests pass (or
   `--no-verify`).

## Ledger

- **Writes:** `kind=syndicate`, `outcome=success|skipped|failure`,
  `detail`="`<transform>` to `k` repos", `data={transform, repos: [{repo,
  outcome, pr}], skipped, failed}` — one entry summarising the whole fan-out.
- **Reads:** nothing.

## Guard & Workspace

- A `Workspace` worktree **per repo**; every `git`/`gh` side effect is an
  `Action(kind="bash", …)` through `Policy`. **Never merges.**
- **Cross-repo blast radius makes Guard's role matter most here.** The
  command-transform is the sensitive surface — only an **allowlisted** fixed
  command runs, never arbitrary shell, and each still routes through Guard. A
  patch/file-op is inert (no execution). Note in the tool's invariants: a
  transform that fails or dirties a repo unexpectedly aborts *that* repo's PR and
  is reported, never pushed.

## CLI surface

```
mysyndicator apply --transform vendor-harness --repos my-* [--base main]
mysyndicator apply --transform patch:fix.diff  --repos a,b,c
mysyndicator apply --transform file:<path>=<content-ref> --repos ...
mysyndicator apply --transform cmd:ruff-format --repos my-* --dry-run
```

## Test plan

- **Happy path:** two fixture repos + a file-op transform; assert both receive
  the file, both open a PR (fake `gh`), and `kind=syndicate`/`outcome=success`
  records two repo entries.
- **Idempotent edge:** one repo already holds the target content; assert it is
  **skipped** (no PR) while the other gets one.
- **Patch-doesn't-apply edge:** a patch that fails on one repo; assert that repo
  is reported `failed` (not forced) while the other still PRs, and the overall
  outcome reflects the partial result.
- Mock the `gh`/`git` boundaries; transforms applied against real temp git repos.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation` (`Workspace`). Reuses
fleet-dispatch's per-repo branch/PR conventions but **not** its LLM path.
Pairs naturally with **MyDriftWatcher**: DriftWatcher *detects* cross-repo
convention drift, MySyndicator *repairs* it in one fan-out (the `HARNESS.md`
re-vendor is the canonical shared use case). Build independently; most valuable
once ≥3 tool repos exist to keep in sync (they do).

**Open questions:**

- **DriftWatcher/Syndicator shared model.** Both operate on "a set of target
  repos + a convention"; DriftWatcher detects, Syndicator repairs. Likely share
  the repo-set + convention descriptor once both exist — flag, don't couple now.
- **Command-transform allowlist.** Which commands are safe to fan out unattended?
  Start with a tiny fixed set (re-vendor, formatter); expand deliberately, each
  addition reviewed — the blast radius is every repo at once.
- **Grey-zone changes** ("mostly mechanical but slightly per-repo"). v0 refuses
  anything it can't apply cleanly and points the user at fleet-dispatch, rather
  than guessing a per-repo edit — the LLM path already exists for that.
