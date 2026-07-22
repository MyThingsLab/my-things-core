# Conventions — how every My[X] tool is built and enforced

This is the *why* behind the build harness. The enforced checklist an agent reads
is [`src/mythings/harness.md`](../src/mythings/harness.md), vendored into each tool
as `HARNESS.md`. This document explains the reasoning and, crucially, **which
mechanical gate backs each rule** — because markdown only advises; a gate
enforces.

**Two archetypes, stop there.** A long-running process (`my-server`,
`my-telegram-bot`, `my-dashboard`'s serving mode) is not the issue-in/PR-out
tool shape `harness.md` describes — its own canonical rules live in
[`src/mythings/service-harness.md`](../src/mythings/service-harness.md).
Everything below this point describes the tool harness; a service differs
only where `service-harness.md` says so explicitly. Per #57's own decision:
stop at two archetypes — a one-off app (`my-raytracer`) is ungoverned, not a
third template.

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
instructions. Per tool, only five seams vary — name, the single Engine call,
tool invariants, the backlog label, and how to verify it end-to-end. Starting a
new tool = filling those.

## Planning-layer ownership: my-planner / my-director / my-architect

Three tools produce backlog-shaped output and nothing currently states which
layer owns what, so this is that statement — not a code change, and not
arbitration logic for a conflict that hasn't been observed:

- **my-director** is, today, the fleet's only working decomposition path:
  a human-in-the-loop, interactive interview (what shipped / what's blocked /
  the ONE critical objective / guardrails) synthesized into one `SessionPlan`
  — an objective plus ordered task-issues. It reads my-planner's latest plan
  through the same read-only ledger seam MyTodo uses, as one input to the
  interview, never by calling my-planner's CLI.
- **my-architect** is designed to be the *unattended* counterpart — same
  objective-to-task-DAG shape as my-director's output, for when no human
  needs to weigh in. As of this writing it is **not yet functional**: the
  repo is genesis-scaffolded but `tool.py` is still the unfilled
  `my-template` stub (`tools_manifest.json` marks it `status: building`, not
  `shipped`, for exactly this reason). Until it's implemented, my-director is
  the only real decomposition path; treat my-architect's CLAUDE.md as a
  design spec, not documentation of current behavior.
- **my-planner** is not a decomposition tool at all — it reads
  my-orchestrator's ranking via the one-way plan-ledger seam and produces a
  priority-ordered *sequence* of already-decomposed backlog items. It never
  calls my-architect's or my-director's CLI, and never invents new task-DAGs
  of its own.

No arbitration logic exists for my-architect and my-director ever producing
conflicting plans for the same objective, and none should be built pre-
emptively. If that conflict is ever actually observed, it is the signal to
design a precedence rule then — not a problem this document is pre-solving.

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
| No planted secrets in diffs/PRs | this doc | `mythings._secrets` pre-commit hook + `ci.yml` step |
| Dependency vulnerabilities surfaced | this doc | `pip-audit` in `ci.yml` (warn-only) + Dependabot |
| Critical bug halts new dispatch | this doc | `fleet_dispatch.py` / `fleet_cycle.py` check for open `critical`-labelled issues |
| Tools agree with the core they import | this doc | `python -m mythings._compat --check` in core's CI |
| Test fakes come from `mythings.testing` | this doc | review: a conftest re-declaring a shipped fake is a bug |
| v1 repo's version and CHANGELOG agree | `release.md` | `check_version_changelog()` in that repo's own pytest suite |
| RELEASE.md rules stay in sync | this doc | drift-check test (`RELEASE.md` == canonical), same shape as harness |
| v1-to-v1 dependency is pinned, not floating | `release.md` | review; `pyproject.toml`/CI install line names an exact tag |

## Filing bugs

Three severity labels, in every repo:

- `bug` — normal, non-urgent. Goes through the regular issue → PR flow.
- `security` — security-relevant but not fleet-blocking on its own.
- `critical` — the bug is a security issue or breaks a core invariant shared
  across the fleet (a `my-things-core` contract, the harness, or anything
  that would let other tools ship broken work on top of it). Filing a
  `critical`-labelled issue in *any* MyThingsLab repo halts new fleet
  dispatch org-wide until it's closed — `fleet_dispatch.py` and
  `fleet_cycle.py` refuse to start new work while one is open. This is a
  soft halt: in-flight workers finish normally, only *new* dispatch stops.

## Core-API coherence

Every v0 tool installs core as `my-things-core @ git+…@main` — unpinned,
floating. That is deliberate (a pin nobody bumps is a lie), but it means the
day core renames or drops a public symbol, every tool breaks silently, one CI
run at a time. `python -m mythings._compat` is the gate that makes that
impossible:

- **Claims.** Each tool records what it needs from core in `tools_manifest.json`
  (`depends_on: ["core:diff", …]`). A **shipped** tool whose claim core no longer
  satisfies is an error. An **unbuilt** tool's unmet claim is *pending* — that
  claim is precisely the prerequisite for building it, so it is reported, never
  fatal.
- **Imports.** With `--workspace <root>`, every `from mythings… import X` in
  every shipped tool's source must resolve against the installed core. This is
  ground truth, where `depends_on` is only a declaration.
- **Environment.** The shared `.venv` installs core editable from *one*
  checkout. Work inside a git worktree of core and `import mythings` still
  resolves to the other tree — so an entry you just added to the manifest is
  invisible, and the check you just wrote silently tests the wrong source. The
  command refuses to run in a core checkout the interpreter is not actually
  serving, and prints the `PYTHONPATH` that fixes it.

Core's CI runs `--check` (claims + environment). The import scan needs sibling
checkouts, so it belongs in `fleet_cycle.py`, not in a single repo's CI.

## Release contract (v1 repos)

The floating-`@main` decision above holds for v0 — most of the fleet, where
build velocity matters more than a stable surface. A small set of repos that
everything else's safety depends on has graduated to **v1**:
`my-things-core`, `my-guard`, `my-director`, `my-fleet`, `my-dashboard`,
`my-reporter`. For these, `@main` pins no longer apply to each other:

- `src/mythings/release.md` (canonical) / `RELEASE.md` (vendored copy in each
  v1 repo) states semver rules, the deprecation window, and CHANGELOG format.
  `python -m mythings._release <workspace>` re-vendors it, exactly mirroring
  `_harness.revendor`.
- Each v1 repo's `pyproject.toml` `version` and `CHANGELOG.md` must agree —
  `check_version_changelog()` in `mythings._release`, exercised by a test in
  that repo's own suite the same way harness drift is checked, not a new CI
  step.
- A v1 repo depending on another v1 repo pins the exact tag
  (`my-things-core @ git+…@v1.0.0`) in both `pyproject.toml` and its CI
  install line, instead of floating on `@main`. `_compat` keeps running
  regardless, as defense-in-depth, not as the primary mechanism for that pair.
- A v1 repo may still float on `@main` for any v0 repo it depends on — the
  pin requirement is v1-to-v1 only.

## Shared test fixtures (`mythings.testing`)

Every tool mocks the same boundaries — the `gh` runner, the Engine, HTTP
`fetch`, real-git worktrees, JSONL ledgers — and for the first ~20 tools each
repo hand-copied its own fakes, which drifted in naming and behavior.
`mythings.testing` is the one shared copy:

- `FakeGh(responses={("issue", "comment"): "url\n", ("pr", "create"): fn})` —
  the `gh` boundary; replies keyed by subcommand prefix (`argv[:2]`, then
  `argv[:1]`), values a string or a `Callable[[argv], str]` for stateful cases;
  an unmatched call raises. Records `.calls`, asserts via `.saw(*prefix)`.
- `ScriptedEngine(reply="", *, data=None)` — records `EngineRequest`s, returns
  one canned `EngineResult`. The old `SpyEngine` is the default (empty) case.
- `fake_fetch(responses, *, default=None)` — URL-substring → bytes/str/JSON.
- `ledger_entry(...)` / `make_ledgers(root, shared=…, dev=…)` — deterministic
  `LedgerEntry` factory and a repo root with shared + dev ledgers.
- `make_git_repo(tmp_path, files=…) -> GitRepo` — a real worktree pushed to a
  bare origin; `GitRepo.read_committed(branch, path)` asserts what was actually
  pushed. Real git (this pattern, from 13 repos) is the standard; don't mock
  git with a recording lambda.
- Fixtures `clean_git_env` and `attended_env` — **not autouse**.

How to consume it (the pilots' proven recipes — pick by what the conftest needs):

- **Plain helpers only** (`FakeGh`, `ScriptedEngine`, factories): just import
  them. No `pytest_plugins` line needed — they're ordinary callables.
- **Fixtures too, no top-level import in conftest**: declare
  `pytest_plugins = ("mythings.testing",)` and re-wrap autouse locally:

  ```python
  @pytest.fixture(autouse=True)
  def _attended(attended_env: None) -> None: ...
  ```

- **Fixtures AND top-level imports in the same conftest**: don't combine an
  import with `pytest_plugins` — the eager import defeats the plugin's
  assertion rewriting and pytest warns on every run. Re-export the fixture by
  aliased import instead (pytest registers it under the *attribute* name), and
  wrap via `getfixturevalue` (ruff F811 rejects the shadowing-param wrapper):

  ```python
  from mythings.testing import attended_env as _shared_attended_env  # noqa: F401

  @pytest.fixture(autouse=True)
  def _attended(request: pytest.FixtureRequest) -> None:
      request.getfixturevalue("_shared_attended_env")
  ```

This is deliberately *not* a `pytest11` entry point: core is a runtime
dependency of every tool, and an entry point would auto-load these fixtures
into every pytest run in the shared venv. The opt-in is greppable and scoped.

The module imports pytest, so it is test-support only — imported from test
suites, never from tool runtime code. Rule: **don't hand-roll a fake that
`mythings.testing` already provides**; domain-specific builders (EPUB payloads,
manifest shapes) stay in the tool's own conftest.

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

## Secret-leak tripwire

`mythings._secrets` (build tooling, not a contract — same status as
`_devledger`/`_harness`) is a cheap regex scan for common credential shapes
(AWS keys, GitHub/Slack tokens, private-key blocks, generic
`api_key = "..."` assignments) run against **added lines only**, so a secret
already sitting in history doesn't re-trigger the gate on every later commit.
`my-template` ships both wiring points, so a new tool inherits them —
existing repos adopt it the same two ways:

- **Pre-commit** (`.pre-commit-config.yaml`): a `local` hook,
  `entry: python -m mythings._secrets scan-staged`, `language: system` —
  catches a planted secret before it's even committed.
- **CI** (`ci.yml`, `pull_request` only): `actions/checkout@v4` needs
  `fetch-depth: 0` so the PR's base SHA is resolvable locally, then
  `python -m mythings._secrets scan-diff-range "<base sha>...<head sha>"`
  scans the code diff, and piping `gh pr view --json title,body` through
  `python -m mythings._secrets scan-text` scans the PR description itself
  (a diff-only scan would miss a secret pasted straight into the PR body).

Both fail hard today (no warn-first grace period): the check is cheap, has a
near-zero false-positive rate against real code, and secrets are exactly the
class of finding where "warn now, gate later" is the wrong trade — see
`my-things-core`'s own `ci.yml`/`.pre-commit-config.yaml` for the wiring.

## Dependency-vulnerability scanning

No repo had a tripwire for a compromised or CVE'd dependency landing in its
own `pip install -e ".[dev]"` closure. `my-template` ships both wiring
points, so a new tool inherits them — existing repos adopt it the same way:

- **CI** (`ci.yml`, right after the test step): `pip install pip-audit &&
  pip-audit` against the environment `pip install -e ".[dev]"` already built —
  no separate lockfile or requirements export needed.
- **Dependabot** (`.github/dependabot.yml`): `pip` + `github-actions`
  ecosystems, weekly.

**Warn-only for now** (`continue-on-error: true` on the CI step) — the
opposite call from the secret-leak tripwire, deliberately. `pip-audit`'s
advisory DB flags plenty of transitive dev-dependency noise (test/lint
tooling, not shipped code) the fleet hasn't triaged yet, and a brand-new gate
with an unknown false-positive rate that hard-fails every PR is worse than no
gate — it trains everyone to `--no-verify`/ignore red CI. Once a few weeks of
warn-only runs show the real signal, flip `continue-on-error` to `false` (or
scope it to only the runtime `dependencies`, which for `my-things-core` is
empty by design) and it becomes a real gate like the rest of this table.

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
2. Fill the five seams in the copied `CLAUDE.md` (a seam-check test in the
   scaffold fails CI while any is left unfilled after the rename).
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
