# mythings-template — design plan

Not a `My[X]` tool — a GitHub **template repo**
(`MyThingsLab/mythings-template`) that resolves the open question both
[my-scaffolder.md](my-scaffolder.md) and [my-drift-watcher.md](my-drift-watcher.md)
flagged independently: copy scaffolding from an existing tool repo, or
maintain a dedicated, never-deployed template? This doc picks the latter.

## Why a dedicated repo instead of copying an existing tool

- **Avoids copying tool-specific drift.** Copying from `my-guard` risks
  pulling in `my-guard`-specific stray values (its `rules.py`, its specific
  test fixtures) that happen to sit in the "reference" repo for unrelated
  reasons.
- **Decouples the scaffold's evolution from any one tool's churn.**
  `my-guard`'s `pyproject.toml`/CI could legitimately drift for
  guard-specific reasons that shouldn't propagate into the next new tool.
- **Gives MyDriftWatcher an actual canonical source.** Its design compares
  every repo's tracked convention files against *something* — a dedicated
  template resolves what that something is, instead of "majority vote
  across whatever repos currently exist."
- **A native human fallback.** GitHub's own "Use this template" button
  works even if MyScaffolder isn't built yet or a human wants to bootstrap
  a tool by hand.

## Contents

Mirrors [`CONVENTIONS.md`](../CONVENTIONS.md)'s "Starting a new tool"
scaffold list, as inert placeholders — nothing here is ever deployed from
this repo directly:

- `pyproject.toml` — package name as a literal `my-x` placeholder,
  `my-things-core` as a dependency, the shared ruff config (E/F/I/UP/B,
  line-length 100).
- `ci.yml` — the canonical hardened workflow: `concurrency:
  cancel-in-progress`, `paths-ignore` for docs/dev-ledger, draft-PR skip,
  `timeout-minutes: 10`, single Linux job.
- `.gitignore`, `LICENSE`, `.pre-commit-config.yaml` (ruff +
  `pytest -m "not slow"`).
- `dev-ledger/` — empty, with a `.gitkeep`.
- `HARNESS.md` — vendored byte-for-byte from `my-things-core`'s canonical
  `src/mythings/harness.md`, so a tool scaffolded from this template passes
  its own drift-check test on the very first commit.
- `tests/test_harness_drift.py` — the drift-check test itself, copied
  verbatim, so every new tool inherits the check automatically rather than
  someone remembering to add it.
- `CLAUDE.md` — `CLAUDE.template.md`'s content with the four seam
  placeholders left literal (`<one line — what this tool does>`, etc.) for
  MyScaffolder to fill programmatically, or a human to fill by hand via
  "Use this template."
- `README.md` — one line: "This is a template repo. Do not deploy from it
  directly — used via MyScaffolder or GitHub's 'Use this template'."

## Ownership & maintenance

Lives under the `MyThingsLab` org, public, same visibility policy as every
other repo. Marked as a GitHub template repo (`gh api repos/{owner}/{repo}
-f is_template=true`, or the "Template repository" checkbox in Settings).
**Not built via the harness** — it's static, human-maintained
infrastructure, not an issue-driven tool with an Engine call. Its own CI
can be minimal (just the drift-check test, trivially passing against
itself) or omitted entirely, since nothing is ever merged *into* main here
except scaffold updates.

Changes to the canonical `HARNESS.md` in `my-things-core` still propagate
the same way as today (re-vendor into every tool's `HARNESS.md`) — this
template repo needs its own copy re-vendored too, as one more instance of
the drift-check-covered set.

## Consumers

- **MyScaffolder** copies from this repo instead of an existing tool (its
  deterministic pre-work step 3 updates to reference `mythings-template`
  by name).
- **MyDriftWatcher** treats this repo's copy of each tracked file as
  canonical instead of computing a majority vote (its pre-work step 3
  updates the same way).
- **A human bootstrapping a tool manually** (before MyScaffolder exists,
  or for a one-off) uses GitHub's "Use this template" button directly, then
  follows [BUILD_GUIDE.md](BUILD_GUIDE.md) from step 3.

## Open questions

- Whether `mythings-template` itself needs a `dev-ledger/` given it's never
  built via the harness — probably not for the repo itself, but it ships
  an *empty* `dev-ledger/` as part of the scaffold contents (for the tool
  that gets created from it). Not decided whether the template repo
  tracks its own meta-changes the same way.
- Who/what re-vendors `HARNESS.md` into this repo when the canonical copy
  changes — today that's a manual step for every tool; this template is
  one more repo in that set, not a new mechanism.
