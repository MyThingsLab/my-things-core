# mythings-core — architecture & contracts

This document is the *why* behind the code. The code carries no docstrings on
purpose; the contract each module upholds lives here so it can be read in one
place, as a reference for the tools built on top.

## The pattern being generalized

MyThingsLab extrapolates a working pattern: a repository developed by a loop of
small workers, each of which

1. reads a unit of work from a backlog (a GitHub issue),
2. runs deterministic pre-work (lint, index, checks) with **no** model call,
3. calls an LLM **once**, only for the step that needs judgment,
4. produces a pull request — **never a merge** (a human, or a permission-scoped
   GitHub App, holds merge authority),
5. appends a structured outcome to a shared ledger so the next run can trust it.

The reference implementation of this pattern hard-coded everything to one repo.
`mythings-core` keeps the shape and removes the assumptions: the ownership map is
derived from the target repo at run time, the backlog is any GitHub project, and
the model backend is swappable behind one interface.

## The four contracts

### `ledger` — shared memory

An append-only JSONL file of `LedgerEntry` records. Append-only is the point:
concurrent tools (and re-runs) can only add, never rewrite, so history is a
trustworthy audit trail. Every record carries `ts`, `tool`, `kind`, `outcome`,
a free-text `detail`, and a `data` dict for tool-specific fields. Readers filter
by `tool`/`kind`; they never mutate.

Why it is in Core and not each tool: `MyKnowledger`, `MyReporter`, and
`MyAdvisor` all reason over the *same* history. One schema, one writer contract.

### `policy` — the guard seam

`Action` describes something a tool wants to do (`kind` + `payload`). A `Policy`
evaluates it to a `PolicyResult` carrying a `Decision`:

- `ALLOW` — proceed silently.
- `ASK` — a human must confirm (an unattended runner treats this as a block).
- `DENY` — never, full stop.

Core defines the types; `MyGuard` provides the rule engine that implements
`Policy`. This keeps the vocabulary shared and the enforcement swappable.

### `engine` — the single LLM seam

`Engine.run(EngineRequest) -> EngineResult` is the **only** place a model is
called anywhere in the system. It is a `Protocol`, so a tool can be built and
tested end-to-end against `NoopEngine` (deterministic, no tokens) before any
real backend exists. The first real backend, `ClaudeCLIEngine` (added
2026-07-07), shells out to the `claude` CLI in headless print mode rather than
an SDK — no new dependency, reuses whatever `claude` auth is already
configured. It never raises: a CLI failure or unparsable reply degrades to an
empty `EngineResult`, the same shape as `NoopEngine`'s empty reply, so every
tool's existing "summarize degrades gracefully" handling covers it without
tool-side changes. Other backends (a hosted API, a local model) can still be
added later, chosen cheapest-capable-first.

### `github` — the substrate adapter

A thin wrapper over the `gh` CLI: list issues, open a PR, read a PR's CI status.
GitHub is chosen deliberately as the execution substrate — Actions gives free
scheduling and throwaway-runner isolation, and a GitHub App gives each tool its
own permission-scoped identity. We do **not** abstract over other forges.

### `isolation` — the sandbox

`Workspace` creates a git worktree from a base ref, yields its path, and cleans
up — so a worker edits an isolated tree, never the live checkout. On a GitHub
Actions runner the machine is already disposable, so `in_github_actions()` lets
a caller skip the worktree when it is redundant.

## What is intentionally *not* here

- No LLM calls beyond the `engine` seam itself — tools still choose when to
  spend the one call `NoopEngine` vs. `ClaudeCLIEngine` makes.
- No scheduler/daemon — GitHub Actions `schedule:` / event triggers are the
  conductor. A tool is a CLI the workflow invokes.
- No multi-forge abstraction.
- No tool logic — `MyGuard`, `MySearcher`, etc. are separate repos that depend
  on this one.
