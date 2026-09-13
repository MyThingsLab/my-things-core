# Changelog

All notable changes to `my-things-core` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/), per the rules in `src/mythings/release.md`
(see `docs/CONVENTIONS.md` for the reasoning).

## [1.2.0] - 2026-09-13

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
