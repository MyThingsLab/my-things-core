# my-things-core

[![CI](https://github.com/MyThingsLab/my-things-core/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-things-core/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-things-core/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-things-core) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

The shared foundation every **MyThingsLab** tool (`My[X]`) is built on.

MyThingsLab is a line of small, composable tools that develop a GitHub
repository as autonomously as possible — calling an LLM **only when a step
genuinely needs judgment**, and running everything else as deterministic code.
`my-things-core` is not one of those tools; it is the SDK they all import.

## The idea

The bet is that an autonomous tool should be *mostly ordinary code*. Where
other designs hand the model the whole job — plan, search, edit, verify,
decide — this one gives it exactly one narrow question and writes the rest
in Python.

That turns out to be a load-bearing choice rather than a stylistic one:

- **It is testable.** `NoopEngine` is a real, deterministic `Engine`. A tool's
  entire skeleton — argument parsing, candidate assembly, validation, the git
  and GitHub side effects — runs and passes its suite with no model, no
  network, and no spend. Only the judgment step needs a real backend.
- **It is auditable.** When something goes wrong, the surface that could have
  behaved non-deterministically is one function call wide.
- **It is priceable.** The billed part of a run is bounded by construction,
  not by a token budget bolted on afterwards.

The corollary is the rule this whole package exists to enforce: **nothing in
`my-things-core` calls an LLM.** `mythings.engine` defines the seam; it does
not cross it.

## The five contracts

Each is a seam a tool plugs into — swap the implementation, keep the
interface. These five are the architecture; everything else in the package is
shared work that happens to live here.

| Module | Contract |
|---|---|
| `mythings.ledger` | Append-only JSONL run history — the shared memory every tool writes to and reads back. It is how independent processes get one trustworthy account of what happened, without a database. |
| `mythings.policy` | `Action` types and a `Decision`: allow / **ask** / deny. `ask` is a first-class state, not an error — it suspends the run and routes the question to a human, which is what makes unattended operation survivable. |
| `mythings.engine` | The `Engine` protocol — the *one* place a model is invoked. `NoopEngine` (deterministic default), `ClaudeCLIEngine` and `GeminiCLIEngine` (shell out to the respective CLI) all ship here. |
| `mythings.github` | A thin `gh`-CLI adapter for issues, PRs, and CI status. GitHub is the execution substrate, not something to abstract over. Tests mock the `gh` process and nothing else. |
| `mythings.isolation` | `Workspace` — a git-worktree sandbox — plus detection of CI, where the runner already *is* the sandbox and a second one would be waste. |

## Shared seams

Beyond the five, every module here was **promoted, not designed**: it earned
its place by already existing, near-identically, in several tools at once.
`mythings.http` replaced a byte-identical private `_http` in four repos;
`mythings.selection` replaced the same candidate-ordering shape written three
times. Promotion answers observed duplication rather than predicting it,
which is why this list grew instead of being specified up front — and why
adopting one of these is usually an import swap, not a refactor.

**Work selection and planning**

| Module | What it gives you |
|---|---|
| `mythings.labels` | The `lane` / `prio` / `kind` / `size` / `state` facet schema, plus `parse`, `validate` and the ranking `sort_key` the whole fleet queues on. |
| `mythings.selection` | The recurring "assemble candidates → one Engine call to order them → validate the reply is a permutation → deterministic fallback under `NoopEngine`" shape, written once. |
| `mythings.plan` | A plan as ordered `PlanTask`s that reference each other by title, so dependencies survive a round-trip through Markdown. |
| `mythings.session` | Durable memory of *a unit of work and its verdict* — what a task was, what became of it, what the next session needs to know. The ledger records events; this records outcomes. |
| `mythings.handoff` | `StageHandoff` — one stage's output made legible to the next, persisted so a cycle can resume rather than restart. |

**Reading code and documents**

| Module | What it gives you |
|---|---|
| `mythings.graph` | A code graph of `Node`/`Edge` plus the questions worth asking of it: `BlastRadius`, `CloneGroup`, `TestGap`, `UntestedInvariant`. |
| `mythings.corpus` | `Document` / `Chunk` / `Citation` and text extraction, so a claim can cite the exact span it came from. |
| `mythings.fetch` | One deterministic, dependency-free URL → clean text path, with robots handling. |
| `mythings.http` | The sibling of `fetch`, deliberately not merged with it: calling a JSON/XML **API**, not scraping a page. |
| `mythings.embed` | An `Embedder` protocol with a dependency-free `HashingEmbedder` default and an `ApiEmbedder` for a real backend. |

**GitHub and operations**

| Module | What it gives you |
|---|---|
| `mythings.projects` | The GraphQL half of GitHub — Projects v2 has no REST surface, so it cannot live in `github.py`, but it keeps the same `Runner` boundary. |
| `mythings.mastery` | The learn-loop's feedback side: graded `Attempt`s appended to a local JSONL ledger, the same append-only discipline as the dev-ledger. |
| `mythings.testers` | A SQLite-backed registry of testers, sessions and turns, for tools with humans on the other end. |
| `mythings.tool` | `BaseToolRunner` — the CLI skeleton a `My[X]` tool subclasses instead of rewriting. |
| `mythings.instructions` | Locating and reading a repo's agent instruction file, wherever it is named. |
| `mythings.logging` | One call wires a logger with two sinks: JSONL for a machine, colorized console for a human. |
| `mythings.testing` | A pytest plugin — `FakeGh`, `ScriptedEngine`, `GitRepo`, ledger fixtures. Imported **only** from test suites, which is why depending on pytest here does not violate the dependency-free-runtime rule. |

## Design rules

- **Deterministic-first.** Nothing here calls an LLM. The `Engine` protocol is
  the only place a model is ever invoked, and it lives behind an interface so
  a tool can run its whole non-LLM skeleton at zero token cost.
- **GitHub-native, not VCS-abstract.** We target GitHub specifically (issues,
  Actions, PRs, App identity). No multi-forge abstraction — that is deferred
  complexity we do not need.
- **Dependency-free runtime.** Shells out to `gh` and `git`; pulls no SDKs.
  Every dependant inherits a tiny footprint. `mythings.testing` is the single
  documented exception, and it never loads at runtime.
- **The public API is contracts only.** `_devledger`, `_harness`, `_compat`
  and friends are build tooling and stay out of `__all__`.

The full rationale — and the pattern this is extrapolated from — is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The fleet-wide conventions and
the Rule→Gate enforcement table are in
[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

## Stability

`my-things-core` is **v1**: real semver, a [`CHANGELOG.md`](CHANGELOG.md)
entry per bump, and deprecate-before-remove on anything in `__all__`. The
contract is [`src/mythings/release.md`](src/mythings/release.md).

Because every tool in the fleet imports this package, a breaking change here
is a fleet-wide event. Adding to `__all__` is cheap; changing or removing
from it is not.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
