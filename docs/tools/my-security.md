---
tool: MySecurity
repo: my-security
package: mysecurity
status: designed
added: 2026-07-08
backlog_label: my-security
engine_call: optional: write a remediation summary from these redacted findings
ledger_kinds: [security]
depends_on: [core:repo_list]
---

# MySecurity — design plan

## Purpose

Continuous security scanning across every repo in the `MyThingsLab` org: leaked
secrets (working tree *and* git history) and vulnerable dependencies. Closes
the "vuln scan / secret-leak detection" fleet safety gap that has been tracked
open since the fleet-dispatch safety review. Package `mysecurity`, backlog
label `my-security`.

This tool **detects and reports only** — it never rotates a secret, never
auto-upgrades a dependency, and never writes the value of a finding anywhere
an LLM or a public issue can read it. See Invariants below; these are the
load-bearing rules for this tool specifically, more so than for most of the
fleet, because the entire point is to *stop* a leak, not create a second one
in its own findings.

## The single Engine call

Optional, same "deterministic scan, judgment only for the write-up" shape as
MyTodo's optional prioritization step. Given a batch of already-redacted
findings (rule id, file, line, commit — never the matched secret or the CVE's
raw advisory text is fine, that's public), it may write a one-paragraph,
plain-English remediation summary per finding group, for the issue body.
Defaults off (`NoopEngine`): the scanners themselves already produce a
severity and a rule id, so v0 is fully usable without a model call at all,
same as MyDriftWatcher.

**Hard rule, not a suggestion:** the Engine call receives only the redacted
finding shape. The literal secret value and the raw file contents around a
gitleaks match are never constructed into a prompt, logged, or passed to
`Engine.run`. This holds regardless of which `Engine` backend is configured —
a local `NoopEngine` is safe by construction, but `ClaudeCLIEngine` shells out
to a real model, so the redaction has to happen upstream of the call, not be
trusted to backend-side discretion.

## Deterministic pre-work

1. List every repo under the `MyThingsLab` org (`gh repo list` — same call
   MyDriftWatcher already needs; if MyDriftWatcher ships first, reuse its
   `github.GitHub.repo_list()` addition instead of re-adding it).
2. For each repo, obtain a full-history local checkout (shallow clones miss
   secrets committed and later removed, which is exactly the case that
   matters — a `git log` diff isn't enough, the *content* of an old commit is
   what a scanner needs to see). Reuse the repo's existing checkout under
   `MyThingsLab/<repo>` when present and up to date; otherwise `git clone`
   into an `isolation.Workspace` and discard it after the run.
3. Run `gitleaks detect --source <path> --report-format json` against the
   full history. Secret scanning is git-history-aware on purpose — see the
   open question below on this being a new CI/toolchain dependency.
4. Run `pip-audit` against each repo's resolved dependencies (`pyproject.toml`
   / lockfile) for known CVEs.
5. **Redact before anything else touches the result**: turn each raw gitleaks
   match into `{repo, file, line, commit, rule_id, redacted_snippet}` where
   `redacted_snippet` keeps only the first/last two characters of the match
   (`sk-a...9f2`) — enough for a human to recognize *which* key without the
   finding itself being a usable credential. Dependency findings need no
   redaction (CVE ids and package/version are already public).
6. Compare against this tool's own last `kind=security` ledger entries for
   the same repo+rule_id+file+line (secrets) or repo+package+CVE (deps); skip
   re-flagging unchanged findings — the same dedupe pattern as MyDriftWatcher.

## Ledger

- **Writes:** `kind=security`, `outcome=clean` (no findings) or
  `outcome=finding`, `detail`="N secret findings, M vulnerable deps in
  <repo>", `data={repo, secrets: [...redacted...], deps: [...]}`. The literal
  secret value is never written to `data` — this is the same boundary as the
  issue body, and the ledger is append-only and readable by every other tool,
  so a leak here is as bad as a leak in a public issue.
- **Reads:** its own prior `kind=security` entries, to dedupe unchanged
  findings across runs (pre-work step 6).

## Guard & Workspace

- No code-changing PR in v0 — pure advisory, same stance as MyDriftWatcher:
  it flags, a human rotates the secret or bumps the dependency. Auto-opening
  a dependency-bump PR (Dependabot-shaped) is a plausible v1, deliberately
  deferred — it would need `Workspace` + `Policy` treatment closer to
  MyCoder's than MyDriftWatcher's, and mixing "detect" with "patch" in v0
  widens the blast radius of getting either wrong.
- On a finding, opens a GitHub issue (not a PR) on the affected repo via
  `gh issue create` — an `Action(kind="bash", ...)`, `ALLOW` by default under
  MyGuard's rules, same pattern as MyDriftWatcher/MyGroomer. The issue body
  template for a secret finding is fixed and reviewed as part of this tool's
  test plan: file + line + commit + rule id + redacted snippet + a rotation
  instruction ("treat as compromised; rotate via `gh secret set`, then purge
  from history") — never the match itself.
- Every MyThingsLab repo is public. That is precisely why the redaction rule
  in pre-work step 5 is not optional: the issue this tool opens is exactly as
  visible as the leak it's reporting on, unless the payload is redacted first.

## CLI surface

```
mysecurity scan [--repos core,my-guard,...] [--secrets-only|--deps-only]
```

## Test plan

- **Happy path (secret):** a fixture repo with a planted fake-but-detectable
  pattern (e.g. an AWS-shaped key regex, not a real credential) committed and
  then removed in a later commit; assert a redacted finding is produced, an
  issue is opened, and — critically — assert the literal planted string is
  **absent** from the issue body, the ledger entry, and any Engine prompt
  constructed during the run.
- **Happy path (deps):** a fixture `pyproject.toml`/lockfile pinning a
  package version with a known CVE (via a stubbed `pip-audit` response, not a
  live query); assert a finding + issue.
- **Edge case (clean):** a fixture repo with no secrets and no vulnerable
  pins; assert `outcome=clean`, no issue opened.
- **Edge case (dedupe):** same finding across two runs; assert only the first
  run opens an issue.
- Mock `github.Runner` and stub the `gitleaks`/`pip-audit` subprocess calls
  (fixed JSON fixtures) — the default suite never shells out to a real
  scanner or hits a live CVE database, same "mock at the system boundary"
  convention every other tool follows. A `slow`-marked integration test may
  run the real binaries if present.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (`repo_list` + `create_issue`,
already needed by MyDriftWatcher/MyGroomer — build after at least one of
those lands so this doesn't duplicate the addition) and `isolation.Workspace`
for throwaway full-history clones. No dependency on any other `My[X]` tool's
logic.

**Open questions (confirm before implementing, not decided here):**
- **New toolchain dependency: `gitleaks` binary in the CI image.** Same
  category of decision as MyTypster's `typst` CLI addition — a new tool the
  harness's CI workflow has to install. `pip-audit` is pure Python and needs
  no such confirmation (it's a normal `dev` extra like `pytest`/`ruff`).
- **Redaction is a one-way, tool-owned decision, not configurable.** Explicit
  choice to *not* expose a `--no-redact` flag or any setting that could
  widen what a finding shows — the alternative (a config that could
  accidentally leak a full secret into a public issue) is worse than the
  inconvenience of always redacting.
- **v0 scope is org repos only.** A local machine's uncommitted `.env` files
  are a real leak surface too, but scanning outside a git repo the tool
  doesn't own crosses into "reads arbitrary local filesystem contents,"
  which is a materially different trust boundary — parked, not folded into
  v0. The nearer-term mitigation for that surface is a `.claude/settings.json`
  permission deny-list (blocking `Read`/`Grep` on `.env*`, `*.pem`,
  `*credentials*`, `*secret*` patterns) at the workspace level, which is a
  config change rather than a tool and doesn't wait on MySecurity shipping.
- **"my-secrets" (a secrets *store*) was considered and rejected as a
  separate tool.** A tool that persists secrets is a liability this fleet
  doesn't need to own — GitHub Actions Secrets (already wired per the
  branch-protection/CI work) and, if ever needed, an external vault (GCP/AWS
  Secrets Manager) already solve storage. MySecurity's job is strictly
  detection of what shouldn't be there, not custody of what should.
