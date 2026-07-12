---
tool: MyCounsel
repo: my-counsel
package: mycounsel
status: designed
added: 2026-07-12
backlog_label: my-counsel
engine_call: optional: classify a deterministic finding as ok/review/block with a rationale
ledger_kinds: [counsel_scan_run, counsel_finding_flagged, counsel_gate_blocked]
depends_on: []
---

# MyCounsel — design plan

## Purpose

A pre-publish compliance gate: scan a repo (or a diff) for secrets, personal
information, and likely-copyrighted material *before* it reaches a public
GitHub push. Package `mycounsel`, backlog label `my-counsel`.

The forcing incident: course-copyrighted lecture PDFs and exam materials were
committed and pushed to the public `MyThingsLab/study` repo, discovered only
after the fact, and required a git-history rewrite plus force-push to remove.
Nothing in the fleet today checks *before* a push. `my-guard` is a generic
rule engine for repo policy; this is the domain-specific gate that knows
about secrets, PII, and copyright, and produces a reviewable verdict — the
same "one job, one contract" shape as every other My[X] tool.

## Two jobs, one scan

- **`scan`** — walks a repo's tracked (or staged) files and returns a list of
  `Finding(path, kind, severity, evidence)`. Deterministic, no Engine call,
  never leaves the machine unless `--classify` is passed.
- **`gate`** — runs `scan`, then (only under `Policy.evaluate(...)`) posts the
  result as a PR comment and fails the check if any `block` finding exists.
  This is the CI/dispatcher-facing surface.

## What it looks for (deterministic layer)

- **Secrets** — high-signal regexes + entropy checks: cloud/API key shapes
  (`ghp_`, `sk-`, AWS-style, Anthropic-style), PEM key blocks, `Bearer`
  headers, `.env`-style `KEY=value` assignments.
- **Personal information** — email addresses, phone numbers, and a
  configurable deny-list of the operator's own identifiers (name, personal
  emails, handles) so a push can never carry "personal stuff used on the
  ecosystem" into a public repo, matching the org's existing
  [never-persist-secrets rule](../CONVENTIONS.md).
- **Likely-copyrighted material** — binary/media files (PDF, image, audio,
  video) over a size threshold; text carrying `©` / `Copyright` /
  `All rights reserved`; third-party `LICENSE` files pulled in from
  elsewhere; SPDX tags naming a license incompatible with the repo's own.

Each finding gets a severity (`info` / `review` / `block`) from static rules
alone — the tool is useful and safe with the Engine entirely off.

## The one Engine call (optional)

Given the findings *only* (capped, redacted evidence snippets) plus
`context = {repo, visibility, purpose}`, classify each into
`ok | review | block` with a one-line rationale and a concrete remediation
(`gitignore`, `redact`, `move-offline`, `add-attribution`, `relicense`).
Judgment only, no side effect — `--offline` skips this entirely and the
deterministic severities still gate on their own, so sensitive content never
has to leave the machine to get a useful answer.

## Invariants

- **Advisory, never destructive.** `mycounsel` reports; it never deletes a
  file or rewrites git history. Fixing a finding (gitignoring a path,
  purging history) stays a human (or explicitly-instructed agent) action.
- **Fail-loud, fail-closed.** Exits non-zero on any `block` finding. If the
  Engine is unreachable during `--classify`, the deterministic severities
  still apply — an absent judgment is not treated as a pass.
- **Local by default.** The only outbound traffic is the opt-in Engine call
  over redacted findings; `--offline` makes the whole run fully local,
  appropriate for scanning genuinely sensitive material.
- **Config-driven, not hardcoded.** `.mycounsel.toml` holds allowlists
  (approved emails/domains, permitted binary types, permitted licenses),
  the personal deny-list, per-kind severity overrides, and the binary size
  threshold — so one operator's identifiers never need to live inside this
  tool's source.

## CLI

```
mycounsel scan  --repo-root . [--staged | --tracked | --all] [--classify] [--json]
mycounsel gate  --repo owner/name --pr N        # Policy-gated PR comment; fails on block
```

`scan` is the local, always-safe command a human runs before `git push` or
that a pre-push hook runs automatically. `gate` is the CI/PR-facing check.

## Where it plugs in

- A **pre-push git hook** on the operator's machine — the earliest, cheapest
  place to catch this.
- A **CI check** (`mycounsel gate`) on every PR across the org, alongside the
  existing `test` gate.
- `fleet_dispatch.py` / `fleet_cycle.py` run `mycounsel scan --staged` before
  a dispatched worker is allowed to open a PR, so no unattended headless
  session can publish a leak the way the `study` repo incident happened.

## Blast radius

Read-only against the repo it scans. Its only side effects (PR comment, CI
failure) are gated by `Policy.evaluate(...).under(unattended=...)`, same as
every other tool's side effects. It holds no credentials beyond what `gh`
already provides for `gate`.

## Open questions

1. **Name** — `my-counsel` (legal-review framing) vs. `my-compliance` vs.
   `my-redactor`. This doc uses `my-counsel`; open to renaming before genesis.
2. **PII deny-list source** — a committed `.mycounsel.toml` allowlist (visible
   in every repo that uses it), or resolved from a local, gitignored
   operator profile so the identifiers themselves are never written into any
   tracked file, including this tool's own config?
3. **Copyright depth for v0** — heuristic-only (binary detection, `©`
   headers, SPDX tags), or include the optional Engine classification from
   day one? Leaning heuristic-only for v0, Engine classification as a fast
   follow-up once the deterministic layer has real usage.
