# Changelog

All notable changes to `my-things-core` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/), per the rules in `src/mythings/release.md`
(see `docs/CONVENTIONS.md` for the reasoning).

## [1.6.0] - 2026-09-14

Since v1.5.0 was tagged, six PRs landed on `main` without a version bump —
`pyproject.toml` kept saying 1.5.0 while the code it names moved on, leaving
no tag for what a dependant pinning "the latest release" would actually get.
Same class of gap as #174, just recurring on new commits instead of old
ones: this release closes it for the current tree, and `check_version_changelog`
now also rejects a repeated `## [X.Y.Z]` heading so a future rerank can't
silently reuse a version the way `[1.2.0]` once did.

**Added — `mythings.handoff`**, the standardized inter-tool handoff contract.
`StageHandoff` carries target symbols, modified files, test targets, and an
Agent Context Pack slice from one fleet-cycle stage to the next (Planner →
Researcher → Scaffolder → Coder → Tester → Reporter); `render_prompt_slice`
keeps the cost to ~100-200 tokens, and `save`/`load` persist handoffs under
`.my-fleet/handoffs/`. Closes #176.

**Added — `mythings.ledger` token telemetry, checkpoints, and `ResumePack`.**
Entries carry standardized `prompt_tokens`/`completion_tokens`/`total_tokens`/
`cost_usd`; `get_checkpoint` synthesizes an attempt-history summary and
`render_resume_pack` renders a ~100-token markdown slice a worker resuming
after an interruption can read instead of replaying the full ledger. Closes
#175.

**Added — `BaseToolRunner.run_issue_workflow` and seam methods**, plus
`GitHub`/`Engine` contract extensions (`build_engine_from_args`,
`parse_json_object`, and matching `GitHub`/`tool` additions) so a My[X] tool
can delegate its issue-pick-through-PR loop to core instead of
re-implementing it per repo.

**Fixed — `GitHub.get_issue` no longer raises when the GraphQL/REST payload
omits `url`**; it now falls back to `""` like every other optional field on
`Issue`.

## [1.5.0] - 2026-09-13

**Added — `mythings.graph`**, deterministic property graph for code, documentation,
and CAD ephemeral worker context. Provides a zero-dependency SQLite-backed relational
substrate (`CodebaseGraph`), recursive CTE graph traversals (`neighbors`,
`k_hop_subgraph`, `blast_radius`), Python AST extraction (`PythonAstExtractor`),
Markdown AST extraction and symbol cross-linking (`MarkdownExtractor`), and
Agent Context Pack generation (`render_context_pack`) to constrain worker blast radius.
Closes #165, #166, #167.

## [1.4.0] - 2026-09-13

**Added — `labels.escalate(labels)`**, the filing-time counterpart to
`sort_key`. A `kind:bug` in `lane:core` or `lane:kernel` comes back carrying
`prio:P0` whatever priority the filer chose, with `Escalation.reason` naming
what changed; everything else is returned untouched with `reason=None`. Ranking
alone only ordered what someone had already prioritized by hand, so a core bug
filed unlabelled still queued behind product backlog. Pure function, no
network; consumers opt in at their filing sites.

## [1.3.0] - 2026-09-13

Released as `1.2.0` by mistake — that version was already taken by the
`mythings.session` entry below, and both landed before either was tagged.

**Changed — `labels.sort_key` now ranks priority above lane.** The key is
`(not critical, prio_rank, lane_rank, -age_days, repo, number)`; it was
`(not critical, lane_rank, prio_rank, …)`. Lane-first made `prio:P0` mean
"first *within its lane*", so a `lane:core` `prio:P3` issue dispatched ahead of
a `lane:kernel` `prio:P0` one — contradicting the schema's own description of
`prio:P0` ("Blocking — nothing else should dispatch ahead of this"). Lane now
decides among equal priorities instead of vetoing them, so a core P0 still
leads the P0s. Callers that sort with `sort_key` see a different order; callers
that only read the tuple's shape are unaffected.

**Added — `critical` is now a `SCHEMA` entry**, bringing it to 23 labels.
`sort_key` already read the label, but it was never in the schema, so `sync()`
never created it and it was absent on repos nobody had labelled by hand. It
stays unprefixed and continues to surface in `Facets.unknown`.

## [1.2.0] - 2026-09-12

Adds `mythings.session` (ADR 0006): an append-only JSONL store for the CAD
loop's units of work — `TaskRecord`, `Verdict`/`Check` (the persisted form of
the acceptance gate's assessment, three-way `passed` included), `GoalRecord`,
and `GoalJournalEntry`. `record()`/`load()` to write and read, `tasks()`/
`goals()` to collapse to the latest line per id, `journal()` to keep every
event, `ready()` (fail-closed on a dangling dependency, same as `plan.ready()`)
for what is dispatchable and `running()` for what an interrupted session has to
recover. `load()` drops a torn final line and raises `CorruptStore` for a bad
line anywhere else. A seam module, not a sixth load-bearing contract, and not
exported from `mythings/__init__` — `Session` there is
`mythings.testers.Session`.

## [1.1.0] - 2026-09-12

Adds `mythings.labels` (ADR 0005): the 22-label CAD schema (`lane:*`,
`prio:*`, `kind:*`, `size:*`, `state:*`) as one canonical data table —
`sync(repo)` to idempotently create/update it on a repo, `parse(labels) ->
Facets` to read it back off a raw label list (unknown labels pass through
untouched), `validate(facets)` to say explicitly why an issue isn't
dispatchable, and `sort_key(issue)` for the fleet's priority queue:
`(not critical, lane_rank, prio_rank, -age_days, repo, number)`, lexicographic
and tuning-constant-free. A seam module, not a sixth load-bearing contract —
same class as `mythings.corpus`/`mastery`/`embed`/`plan`.

## [1.0.0] - 2026-07-20

First stable release. Baseline of everything the fleet already depended on
via `@main` before this repo adopted the release contract: the five
contracts (`ledger`, `policy`, `engine`, `github`, `isolation`), the build
tooling (`_harness`, `_manifest`, `_devledger`, `_compat`, `_secrets`), and
the shared test fixtures in `mythings.testing`. No behavior changes in this
release — it exists to establish the tag `my-guard`, `my-director`,
`my-fleet`, `my-dashboard`, and `my-reporter` pin against.

Adds the release contract itself: `src/mythings/release.md` (canonical
policy) and `mythings._release` (RELEASE.md vendoring + version/CHANGELOG
coupling check), mirroring the existing `harness.md`/`_harness` pattern.
