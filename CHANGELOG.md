# Changelog

All notable changes to `my-things-core` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/), per the rules in `src/mythings/release.md`
(see `docs/CONVENTIONS.md` for the reasoning).

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
