# Building a My[X] tool from its design doc

Generic, tool-agnostic instructions for turning any doc in this directory
into a shipped repo. This covers only the *how*; *which* tool and *in what
order* stays in [README.md](README.md)'s "Recommended build order."

## Repo layout

**One repo per tool** — confirmed, matching the existing convention
(`my-guard` is already its own repo). `my-things-core` stays the only
shared dependency between tools; no monorepo.

## Steps, per tool

1. **Check for unresolved core-contract additions first.** Several docs
   flag new `github.GitHub` methods they need — see the consolidated list
   below. Land those in `my-things-core` as their own reviewed PR *before*
   starting a tool that depends on one; don't add a method reactively
   mid-tool.
2. **Scaffold from [`mythings-template`](mythings-template.md)** — use
   GitHub's "Use this template" button (or MyScaffolder, once it exists) to
   copy `pyproject.toml`, `ci.yml`, `.gitignore`, `LICENSE`,
   `.pre-commit-config.yaml`, `dev-ledger/`, `HARNESS.md`, and the
   drift-check test in one step. Don't copy from an existing tool repo —
   that risks pulling in tool-specific stray content, which is exactly why
   the template repo exists.
3. **Fill `CLAUDE.md`** from `CLAUDE.template.md`, transcribing straight out
   of the design doc: "Purpose" → purpose line, "The single Engine call" →
   that seam verbatim, "Guard & Workspace" → invariants, "Purpose" header's
   backlog label → backlog label. A design doc already contains everything
   `CLAUDE.md` needs — this step is transcription, not invention.
4. `pip install -e ../my-things-core -e ".[dev]" && pre-commit install`.
5. **TDD from the doc's "Test plan" section**, in the order given: happy
   path first (Engine reply scripted exactly as the doc's Engine-call
   section describes), then the edge case. Get each red, then green.
6. **Implement "Deterministic pre-work" in the numbered order given** — the
   docs already sequence these steps deliberately (e.g. skip-checks before
   expensive work); don't reorder without a reason.
7. **Wire the one Engine call** exactly to the doc's input/output spec.
   The `NoopEngine` fallback must match what the doc specifies verbatim
   (e.g. MyKnowledger prints raw excerpts, MyTester emits a fixed
   placeholder test) — this fallback is itself part of the contract, not a
   free choice, since it's what makes the tool testable without tokens.
8. **Wire Guard/Policy** per "Guard & Workspace": every `git`/`gh` side
   effect becomes an `Action`, routed through `Policy.evaluate()` before
   executing — never call `gh`/`git` directly from tool logic.
9. **Ledger** — write exactly the `kind`/`outcome`/`data` fields the doc
   specifies. If implementation reveals a field is missing, update the doc
   first, then the code — the doc is the spec, not documentation after the
   fact.
10. Open the tool's own PR (never merge), get CI green, close with a
    `dev-ledger` entry per [`PROVENANCE.md`](../PROVENANCE.md)'s ritual.

## Core additions needed across this batch

Five separate docs each flag a new `github.GitHub` method in isolation.
Consolidated here so they can be reviewed and added as **one batch PR** to
`my-things-core`, instead of piecemeal as each tool happens to need one:

| Method | Needed by | Purpose |
|---|---|---|
| `diff(pr)` | MyReviewer, MyDescriber | fetch a PR's unified diff |
| `pr_edit(pr, title, body)` | MyDescriber | update a PR's title/body |
| `create_issue(title, body)` | MyGroomer | open a sub-issue |
| `add_labels(issue, labels)` | MyGroomer | tag an issue |
| `list_labels()` | MyGroomer | fetch the repo's label set |
| `repo_create(name, ...)` | MyScaffolder | create a new repo under the org |
| `repo_list(org)` | MyDriftWatcher | list repos under the org |
| `get_file_contents(repo, path)` | MyDriftWatcher | fetch one file, no clone |

All eight are small, same-pattern thin wrappers (mirroring the shape of the
existing `list_issues`/`open_pr`/`pr_status`) — but per the workspace's
architectural-change rule, the batch itself should be proposed and
confirmed as one deliberate PR before any consuming tool's build starts,
not accreted tool-by-tool without a single point of review.

## What these instructions deliberately don't cover

- **Judgment calls.** Each doc's "Open questions" section needs a decision,
  not an instruction — resolve those before starting that tool, don't
  implement around them.
- **Cross-tool build order.** See [README.md](README.md)'s "Recommended
  build order" — this doc is order-agnostic by design so it doesn't drift
  out of sync with that list.
- **MyCoder's and MyAdvisor's Engine-call quality.** No instruction fixes
  what `NoopEngine` can't validate; both wait on a real backend regardless
  of how carefully the plumbing is built.
