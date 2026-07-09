---
tool: MyGrapher
repo: my-grapher
package: mygrapher
status: designed
added: 2026-07-05
backlog_label: my-grapher
engine_call: none
ledger_kinds: [graph]
depends_on: [tool:my-searcher]
---

# MyGrapher — design plan

## Purpose

Keeps a repo's `graphify-out/` knowledge graph fresh and exposes
`query`/`path` access as a shared resource, so other tools (MySearcher,
MyReviewer, MyGroomer) can stop reimplementing their own naive relevance
indexes. Package `mygrapher`, backlog label `my-grapher`. Wraps the
`graphify` skill's underlying `graphifyy` pip package CLI — shelling out to
it the same way other tools shell out to `git`/`gh`, per "dependency-free
runtime: shell out, don't pull SDKs."

## The single Engine call

**None — by design, not by convenience.** graphify's own pipeline calls an
LLM during initial extraction and in `--mode deep`/`explain`. If MyGrapher
invoked those paths, it would be importing hidden model calls, breaking
the harness's one-Engine-call-per-tool invariant. MyGrapher therefore never
performs an initial build — see the invariant below — and only ever runs
`graphify --update`/`--watch`'s incremental refresh, which graphify's own
docs describe as requiring no LLM call.

## Deterministic pre-work

1. Check whether `graphify-out/graph.json` already exists for the target
   repo.
2. **Invariant: MyGrapher refuses to bootstrap a graph.** If
   `graphify-out/` doesn't exist, it does not run an initial build — that
   requires a human (or an interactive agent session with model access) to
   run `/graphify` once, out of band, before MyGrapher can maintain it.
   This keeps MyGrapher's own runs LLM-free and CI-safe, at the cost of a
   one-time manual bootstrap per repo.
3. If it exists, run `graphify <path> --update --no-viz` to refresh
   incrementally (new/changed files only).
4. Optionally run `graphify query "<question>"` / `graphify path <a> <b>`
   against the refreshed graph and return the result as structured data.

## Ledger

- **Writes:** `kind=graph`, `outcome=success|skipped`, `detail`="updated
  graph (+N nodes, +M edges)" or "skipped: no existing graph", `data={
  nodes, edges, communities, query_result}`. `outcome=skipped` covers the
  "refuses to bootstrap" case (step 2) — not a failure, a deliberate no-op.
- **Reads:** nothing — each refresh is independent of ledger history.

## Guard & Workspace

- No `isolation.Workspace` — MyGrapher doesn't edit source, only reads the
  repo tree and writes to `graphify-out/`.
- Whether `graphify-out/` is committed to the repo or left gitignored and
  regenerated per CI run is an open question (below); in the gitignored
  case there is nothing to PR, ever, and MyGrapher opens no PR. If a future
  decision commits the graph, that would need the standard `Workspace` +
  PR path like MyTester, not decided here.
- No `Action`/`Policy` involvement for the refresh path itself (no git/gh
  side effects); an optional `--comment` flag posting graph stats to an
  issue would follow the same `Action(kind="bash", ...)` → `Policy` pattern
  as MyReporter/MySearcher's comment paths.

## CLI surface

```
mygrapher refresh --repo <path>
mygrapher refresh --repo <path> --query "<question>"
```

## Test plan

- **Happy path:** a fixture repo with an existing `graphify-out/graph.json`
  and a fake `graphifyy` CLI runner (mocked boundary, same style as
  `github.Runner`) returning updated node/edge counts; assert
  `kind=graph`/`outcome=success` with the returned stats, and that a
  `--query` flag's result plumbs through unchanged.
- **Edge case (no existing graph):** `graphify-out/` absent; assert no
  attempt to bootstrap (verifies the "never bootstraps" invariant — the
  fake runner should see zero build-mode invocations), `outcome=skipped`,
  `detail` explains a human must run `/graphify` once first.
- Mock only the `graphifyy` CLI subprocess boundary, never the file-
  existence check itself.

## Dependencies & build order

Depends on core `ledger` only for the refresh path (no `policy`/`github`
needed unless `--comment` is used). Depends on the `graphify`/`graphifyy`
package being installed and a graph having been bootstrapped once, out of
band — an external tool dependency, flagged the same way MyTelegramBot's
Telegram dependency was flagged. Build after MySearcher: the natural
follow-up is retrofitting MySearcher's (and later MyReviewer's) naive
shortlist step to prefer `mygrapher.query()` when `graphify-out/` exists,
falling back to the original naive method otherwise — a design already
noted as an open question in [my-searcher.md](my-searcher.md).

**Open questions:**
- **Commit vs. regenerate `graphify-out/`.** Committing ships the graph
  with the repo (consistent with the provenance principle that build
  artifacts should travel with the tool) but bloats history with
  machine-generated JSON on every refresh. Regenerating per CI run avoids
  that but means the graph never exists outside a live run, so
  `mygrapher.query()` can't be called standalone by a human afterward
  without re-running it. Leaning toward gitignored + regenerate-per-run for
  v0, but not decided.
- Whether `--watch` (continuous, non-CI mode) has any use inside the
  harness's one-shot-CLI-per-Action-run model, or whether `--update`
  (one-shot) is the only mode MyGrapher ever needs — assumed the latter,
  since the harness has no daemon by design (per `ARCHITECTURE.md`).
