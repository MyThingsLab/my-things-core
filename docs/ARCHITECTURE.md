# my-things-core — architecture & contracts

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
`my-things-core` keeps the shape and removes the assumptions: the ownership map is
derived from the target repo at run time, the backlog is any GitHub project, and
the model backend is swappable behind one interface.

## The five contracts

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

"Cheapest-capable-first" has a concrete knob: `ClaudeCLIEngine(model=...)`
passes `--model` to the CLI, so a narrow, classification-shaped call (an
orchestrator tie-break, a report summarize) can run on a cheaper model than a
call that writes real code. A tool exposes this as an optional `--engine-model`
flag flowing through a small `build_engine(name, *, model)` factory in its own
CLI — the factory stays a per-tool ~5-line snippet rather than a core export,
so this SDK keeps its dependency-free, contracts-only public API. The flag
defaults to unset (the CLI's own default model), so wiring it in never changes
behavior; picking an actual cheap default for a given tool is that tool's
separate, opt-in decision, never applied to a safety-critical call (e.g.
`MyGuard`'s allow/ask/deny fall-through) by default.

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

## Utilities beyond the five contracts

Not every shared module is a contract — a contract is a swappable interface
(`Protocol` or thin adapter) another repo builds against. Some modules are
just shared plumbing every tool would otherwise reimplement:

- `logging` — one call, `configure(tool, json_path=..., console=...)`, wires a
  standard-library `Logger` with two independent sinks: JSONL to a file (for a
  later `Engine` call, or a human running `jq`, to read back) and colorized
  text to stderr (for a human watching a terminal). Distinct from `ledger`:
  `ledger` is the append-only *outcome* record a tool's own logic reasons
  over; `logging` is diagnostic noise during a run that nothing downstream
  depends on. Deliberately built on `logging.Logger` rather than a bespoke
  type, so it composes with any library that already logs through the
  standard library.

- `testers` — the fleet's only notion of a *second person*. Every other module
  assumes a single principal: `ledger` is one global append-only file, and the
  one tool that authenticates (`my-server`) does it with one shared token. To
  let outside testers explore the fleet through `my-telegram-bot`, three things
  are needed that nothing else provides: identity (`register` /`authenticate` /
  `by_chat_id`, storing only a token's sha256 — the raw token is returned once
  and never written), resumable per-tester state (`start_session` /
  `append_turn` / `resume`, replayed by `(session_id, seq)`), and a hard cap on
  Engine spend by someone who isn't the operator.

  Backed by stdlib `sqlite3`, so the runtime stays dependency-free; WAL plus a
  busy timeout covers the real access shape (the bot polling while the server
  reads). The module is **inert until constructed** — no import-time file or
  network access, exactly like `Ledger(path)`.

  **The quota is fail-closed, and that lives in one statement.**
  `reserve_engine_call` is a single `UPDATE … WHERE enabled = 1 AND engine_used
  < engine_quota`, decided by `rowcount`: the guard is in the `WHERE` clause, so
  a read-then-write race cannot oversell (a naive read-then-write grants ~96
  calls against a quota of 50 under six processes — each one billed). Callers
  reserve *before* spending, never after, so a crash mid-call over-counts (safe)
  rather than over-spends (not). No row updated means refusal — the default
  answer is no, mirroring `TelegramPolicy`'s deny-on-timeout.

  `ledger_for(tester)` hands back an ordinary `Ledger` on a per-tester path, so
  tester activity is isolated additively: no existing global-ledger reader
  changes.

## What is intentionally *not* here

- No LLM calls beyond the `engine` seam itself — tools still choose when to
  spend the one call `NoopEngine` vs. `ClaudeCLIEngine` makes.
- No scheduler/daemon — GitHub Actions `schedule:` / event triggers are the
  conductor. A tool is a CLI the workflow invokes.
- No multi-forge abstraction.
- No tool logic — `MyGuard`, `MySearcher`, etc. are separate repos that depend
  on this one.
