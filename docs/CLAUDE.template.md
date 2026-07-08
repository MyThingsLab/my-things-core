# my-<x> — agent instructions

You are developing **my-<x>**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** <one line — what this tool does>
- **The single Engine call:** <the one judgment step delegated to a model, or
  "none — deterministic">
- **Invariants / rules:** <what must always hold; what this tool may never do>
- **Backlog label:** <the GitHub issue label it picks up>
- **Verify:** <the safe command(s) that prove the tool works end-to-end —
  typically an `--engine noop` dry run — beyond pytest>
