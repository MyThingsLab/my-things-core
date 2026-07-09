---
tool: MyChangelogger
repo: my-changelogger
package: mychangelogger
status: shipped
added: 2026-07-05
backlog_label: my-changelogger
engine_call: none
ledger_kinds: [changelog]
depends_on: []
---

# MyChangelogger — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-changelogger's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-changelogger/README.md`](../../../my-changelogger/README.md) and
> [`my-changelogger/CLAUDE.md`](../../../my-changelogger/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.

## Purpose

Turns `dev-ledger` `kind=ship` (and related) entries into a `CHANGELOG.md`
section and opens a PR. Package `mychangelogger`, backlog label
`my-changelogger`.

## The single Engine call

None — deterministic formatting only, same as MyReporter's default path.
Ledger entries already carry a one-sentence `detail`; this tool arranges
them under conventional-changelog-style headings, it doesn't compose prose.

## Deterministic pre-work

1. Read the target repo's `dev-ledger/*.jsonl`, sorted by `ts`.
2. Take entries since the last `kind=changelog` entry this tool wrote (or
   all-time on first run) — same incremental-window pattern as MyReporter
   and MyWiki.
3. Group by `kind`: `ship` → "Shipped", `build` → "Added/Changed", `fix` →
   "Fixed", `decision` → omitted (internal rationale, not user-facing).
4. Render as a new `## [unreleased]` (or `## [X.Y.Z] - date` if
   `--version` given) section, prepended to `CHANGELOG.md` (create the file
   with a standard header if it doesn't exist yet).

## Ledger

- **Writes:** `kind=changelog`, `outcome=success|skipped`, `detail`="added
  entry for <version|unreleased>", `data={version, entries_count, pr}`.
- **Reads:** its own last `kind=changelog` entry (incremental window) plus
  the `dev-ledger` stream since then.

## Guard & Workspace

- Uses `isolation.Workspace` exactly like MyTester: checkout, edit
  `CHANGELOG.md`, commit, push a branch, open a PR — never merge.
- Every `git`/`gh` side effect is an `Action(kind="bash", ...)` through
  `Policy`, same as MyTester; MyGuard's defaults allow it (no
  merge/force-push/protected-branch pattern).
- Touches exactly one file (`CHANGELOG.md`); never edits source.

## CLI surface

```
mychangelogger update [--version X.Y.Z] [--repo owner/name] [--base main]
```

## Test plan

- **Happy path:** a fixture `dev-ledger` with `ship`+`fix` entries since the
  last changelog entry; assert the generated section groups them correctly
  and a PR is opened with the expected diff.
- **Edge case (nothing new):** no entries since the last `kind=changelog`;
  assert no worktree/PR is created, `outcome=skipped`.
- Mock `github.Runner`; worktree/git operations run against a real
  throwaway temp repo, same convention as MyTester's test plan.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github`, `isolation`. Low complexity —
similar shape to MyTester's PR path but editing a single well-understood
file instead of writing a test. Reasonable to build early, right after
MyReporter (shares its ledger-reading conventions) since it's simple and
immediately useful once even one `ship` entry exists.

**Open questions:**
- Version numbering: MyChangelogger assumes the caller supplies `--version`
  at release time and defaults to an `[unreleased]` rolling section
  otherwise — it does not infer semver bump size from ledger content; that
  would be a judgment call and isn't worth an Engine call for now.
- Whether `decision` entries belong in a public changelog at all (they're
  currently omitted) — flagged as a default worth revisiting if users ask
  "why was X done this way" from the changelog itself.
