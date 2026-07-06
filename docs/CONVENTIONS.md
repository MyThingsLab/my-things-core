# Conventions — how every My[X] tool is built and enforced

This is the *why* behind the build harness. The enforced checklist an agent reads
is [`src/mythings/harness.md`](../src/mythings/harness.md), vendored into each tool
as `HARNESS.md`. This document explains the reasoning and, crucially, **which
mechanical gate backs each rule** — because markdown only advises; a gate
enforces.

## Two layers, mirrored from runtime

MyThingsLab's runtime has an abstract vocabulary (`mythings-core` contracts) and
an enforcer (`MyGuard`). The *build* harness has the same two layers one level up:

- **Advisory** — CLAUDE.md hierarchy + this doc + `harness.md`. States intent.
- **Enforcing** — ruff, pytest, CI, branch protection, hooks, and MyGuard itself.
  Guarantees compliance regardless of whether an agent chose to comply.

The design rule: **never ship an advisory rule without a gate behind it.**

## What is shared vs. what varies per tool

Shared (never re-authored): the five contracts, these conventions, the CI
workflow, the provenance ritual, org/visibility placement, and the base agent
instructions. Per tool, only four seams vary — name, the single Engine call,
tool invariants, and the backlog label. Starting a new tool = filling those.

## Rule → gate

| Rule | Advisory (markdown) | Mechanical gate |
|---|---|---|
| Code style | `harness.md` | ruff in CI + `.pre-commit-config.yaml` |
| Tests green | `harness.md` | pytest in CI + branch protection (required check) |
| Local-first TDD | `harness.md` | pre-commit runs `ruff` + `pytest -m "not slow"` |
| One Engine call | `ARCHITECTURE.md` | review; no model imports outside the seam |
| PR, never merge | `harness.md` | branch protection (PR required) + App perms + MyGuard |
| Provenance per session | `PROVENANCE.md` | (deferred) `Stop` hook |
| CI hygiene / Linux-only | `harness.md` | the `ci.yml` itself |
| All-public / no surprise bill | this doc | org default visibility + $0 spending limit |
| Isolated from other ventures | `harness.md` | org placement (`MyThingsLab`) |
| Harness rules stay in sync | this doc | drift-check test (`HARNESS.md` == canonical) |

## The CLAUDE.md hierarchy

Loaded outermost → innermost:

1. `~/.claude/CLAUDE.md` — personal, all projects. **Keep MyThingsLab rules out of
   here** so they don't leak into unrelated work.
2. `MyThingsLab/CLAUDE.md` — workspace-level, when working across both repos.
3. `<repo>/CLAUDE.md` — travels with a standalone clone; inherits `./HARNESS.md`
   and fills the per-tool seams. This is the one that must be self-contained.

`@path` imports keep things DRY *within* the workspace but don't resolve for a
lone clone — hence each tool **vendors** `HARNESS.md` rather than importing it,
with a drift-check test failing CI if the copy goes stale.

## Starting a new tool

1. Copy the scaffold (pyproject, `ci.yml`, `.gitignore`, LICENSE, `.pre-commit-config.yaml`,
   `dev-ledger/`, `HARNESS.md`) from an existing tool.
2. Copy [`CLAUDE.template.md`](CLAUDE.template.md) to the repo root as `CLAUDE.md`
   and fill the four seams.
3. `pip install -e ../mythings-core -e ".[dev]" && pre-commit install`.
4. Red → green → refactor locally; open a PR; let CI gate it.
