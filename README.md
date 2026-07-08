# my-things-core

[![CI](https://github.com/MyThingsLab/my-things-core/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-things-core/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-things-core/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-things-core) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

The shared foundation every **MyThingsLab** tool (`My[X]`) is built on.

MyThingsLab is a line of small, composable tools that develop a GitHub
repository as autonomously as possible — calling an LLM **only when a step
genuinely needs judgment**, and running everything else as deterministic code.
`my-things-core` is not one of those tools; it is the SDK they all import.

## What it provides

Four contracts. Each is a seam a tool plugs into — swap the implementation, keep
the interface.

| Module | Contract | Status |
|---|---|---|
| `mythings.ledger` | Append-only JSONL run history — the shared memory every tool writes to and reads back. | implemented |
| `mythings.policy` | `Decision` (allow/ask/deny) + `Action` types that `MyGuard` evaluates against. | implemented |
| `mythings.engine` | The `Engine` protocol — the *one* seam where an LLM is called. `NoopEngine` (deterministic default) and `ClaudeCLIEngine` (shells out to `claude -p`) both ship here. | implemented |
| `mythings.github` | Thin `gh`-CLI adapter for issues, PRs, and CI status. GitHub is the execution substrate, not an abstraction. | implemented |
| `mythings.isolation` | `Workspace` — a git-worktree sandbox, and detection of GitHub Actions (where the runner *is* the sandbox). | implemented |

## Design rules (why it looks like this)

- **Deterministic-first.** Nothing here calls an LLM. The `Engine` protocol is
  the only place a model is ever invoked, and it lives behind an interface so a
  tool can run its whole non-LLM skeleton with zero token cost.
- **GitHub-native, not VCS-abstract.** We target GitHub specifically (issues,
  Actions, PRs, App identity). No multi-forge abstraction — that is deferred
  complexity we do not need.
- **Dependency-free core.** Shells out to `gh` and `git`; pulls no SDKs. Every
  tool that depends on `my-things-core` inherits a tiny footprint.

The full rationale — and the pattern this is extrapolated from — is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
