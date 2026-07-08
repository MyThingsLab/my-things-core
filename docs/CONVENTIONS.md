# Conventions — how every My[X] tool is built and enforced

This is the *why* behind the build harness. The enforced checklist an agent reads
is [`src/mythings/harness.md`](../src/mythings/harness.md), vendored into each tool
as `HARNESS.md`. This document explains the reasoning and, crucially, **which
mechanical gate backs each rule** — because markdown only advises; a gate
enforces.

## Two layers, mirrored from runtime

MyThingsLab's runtime has an abstract vocabulary (`my-things-core` contracts) and
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
| Coverage reported | this doc | `pytest --cov` in `ci.yml` → Codecov upload + README badge |
| All-public / no surprise bill | this doc | org default visibility + $0 spending limit |
| Isolated from other ventures | `harness.md` | org placement (`MyThingsLab`) |
| Harness rules stay in sync | this doc | drift-check test (`HARNESS.md` == canonical) |

## Coverage & badges

Every repo's `ci.yml` runs `pytest --cov=<pkg> --cov-report=xml` and uploads the
result with `codecov/codecov-action@v4` (`token: ${{ secrets.CODECOV_TOKEN }}`,
`slug: ${{ github.repository }}`). The upload **soft-fails** — `fail_ci_if_error`
defaults false — so a repo without Codecov wired up still gets a green build.

Each README carries a fixed badge row under the H1: **CI · Codecov · Python
3.11+ · MIT**. `my-template` ships all of this, so a new tool inherits it with
the `<pkg>` rename. The only manual step is one-time and owner-only: add the
repo on codecov.io and set the secret —
`gh secret set CODECOV_TOKEN -R MyThingsLab/<repo>`. A token is **never**
committed.

## The CLAUDE.md hierarchy

Loaded outermost → innermost:

1. `~/.claude/CLAUDE.md` — personal, all projects. **Keep MyThingsLab rules out of
   here** so they don't leak into unrelated work.
2. `MyThingsLab/CLAUDE.md` — workspace-level, when working across both repos.
3. `<repo>/CLAUDE.md` — travels with a standalone clone; inherits `./HARNESS.md`
   and fills the per-tool seams. This is the one that must be self-contained.

`@path` imports keep things DRY *within* the workspace but don't resolve for a
lone clone — hence each tool **vendors** `HARNESS.md` rather than importing it,
with a drift-check test failing CI if the copy goes stale. After editing the
canonical `harness.md`, sweep every sibling checkout in one command instead of
hand-copying: `python -m mythings._harness <workspace-root>` (add `--check` to
just report drift, exit 1 if any copy is stale).

## Starting a new tool

1. Copy the [`my-template`](../../my-template) scaffold (pyproject, `ci.yml`,
   `.gitignore`, LICENSE, `.pre-commit-config.yaml`, `dev-ledger/`, `HARNESS.md`,
   the drift-check test) to `../my-<x>` and replace the `template` placeholder —
   see its README for the exact rename. `my-template` mirrors
   [`CLAUDE.template.md`](CLAUDE.template.md) as its `CLAUDE.md`.
2. Fill the four seams in the copied `CLAUDE.md`.
3. `pip install -e ../my-things-core -e ".[dev]" && pre-commit install`.
4. Red → green → refactor locally; open a PR; let CI gate it.

## `docs/tools/<name>.md` goes historical at first ship

Each doc under `docs/tools/` is a **pre-build design plan** — written to think
through a tool before its repo exists. Once that tool ships, the doc is frozen:
add a one-line historical banner pointing at the tool's own `README.md` /
`CLAUDE.md`, and stop editing it for ordinary feature work. A CLI flag, a new
render mode, an internal refactor — none of that touches core; it's a
single-repo, single-PR change in the tool.

Come back and edit the frozen doc only for something genuinely cross-tool: a
new Engine-seam pattern other tools should copy, a new core dependency, a
change to the tool's five-seam contract itself. Rule of thumb: if the change
is describable entirely inside the tool's own repo, it doesn't belong in core.
