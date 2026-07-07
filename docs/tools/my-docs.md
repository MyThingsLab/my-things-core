# MyDocs — design plan

## Purpose

Keeps `MyThingsLab/mythingslab.github.io` — the fleet's technical
documentation site — in sync with the fleet itself: one docs page per
`My[X]` tool, refreshed from that tool's `README.md` and `CLAUDE.md` filled
seams whenever they change, plus an architecture overview page sourced from
`mythings-core/docs/`. Package `mydocs`, backlog label `my-docs` (consumed
from a workspace-level tracking issue — there is no single per-run target
repo the way most tools have one; the *source* is every `MyThingsLab` repo,
the *destination* is always `mythingslab.github.io`).

MyDocs is deliberately narrow: it publishes what a tool's own README/
CLAUDE.md already say, in a consistent site layout. It does not review,
critique, or invent capability descriptions — that discipline keeps its one
Engine call a formatting/prose step, not a judgment call about what a tool
does.

## The single Engine call

Required: "write or update this tool's docs page from its README and filled
CLAUDE.md seams, matching the style of an existing docs-site page."

- **Input:** the target tool's `README.md` + `CLAUDE.md` verbatim, plus one
  existing docs-site page as a style anchor. `context = {"tool": name,
  "repo": "MyThingsLab/<repo>"}`.
- **Output:** `data = {"page": {"path": str, "content": str}}` — one
  markdown file (front matter + body) for `_tools/<name>.md` on the docs
  site. The model may only draw on the given README/CLAUDE.md content — no
  claims about behavior not stated in either source (same cite-only
  discipline as MyWiki/MyKnowledger, applied to a tool's own docs instead of
  ledger history).
- Against `NoopEngine`: degrades to copying the README verbatim under a
  templated front matter (`title`, `repo` link) — honest degrade, no
  fabricated description.

## Deterministic pre-work

1. Enumerate `MyThingsLab` org repos (`gh repo list MyThingsLab`), excluding
   the docs site itself and any repo without a `CLAUDE.md` (i.e. not a
   `My[X]` tool — `mythings-core`, `mythingslab.github.io`, `fleet-dispatch`
   get their own non-per-tool pages, not this loop). There is no existing
   core helper for this enumeration; MyDocs owns it directly for now — a
   candidate to promote into `mythings-core.github` only if a third tool
   needs the same "list every fleet repo" step (see Open questions).
2. For each tool repo, fetch `README.md` + `CLAUDE.md`, hash both, and
   compare against the hash recorded in that tool's last `kind=docs_sync`
   ledger entry (or the docs-site page's own front matter, if the ledger
   has no record — e.g. the docs site was hand-edited).
3. Build the **stale list**: tools whose hash changed since the last sync.
   If the stale list is empty, **skip the Engine call entirely** — no PR,
   `outcome=skipped` — the same "nothing changed, don't spend a call"
   short-circuit MyChangelogger and MyDriftWatcher already use.
4. One Engine call **per stale tool** (the harness's one-call-per-run rule
   holds per tool, same as MyResearcher's `brief`/`plan` split), not one
   call for the whole batch — keeps each page's context small and avoids
   one tool's prompt crowding out another's.

## Ledger

- **Writes (per tool synced):** `kind=docs_sync`, `outcome=success|skipped`,
  `detail`="docs page for `<tool>`", `data={repo, page_path,
  readme_hash, claude_md_hash, pr_url}`.
- **Reads:** each tool repo's `README.md`/`CLAUDE.md` (read-only) and its own
  prior `kind=docs_sync` entries (for the staleness hash compare).

## Guard & Workspace

One side effect per stale tool: a **committed PR via `Workspace`** against
`mythingslab.github.io` — writes/updates `_tools/<name>.md` in an isolated
worktree and opens a PR (the same `isolation` + `github.open_pr` path every
other PR-opening tool uses), routed through `Action(kind="fs-write", ...)` →
`Policy.evaluate()`, `ALLOW` by default. All stale tools in one run share
**one PR** (one commit per tool's page) rather than one PR per tool, to
avoid a burst of near-identical PRs when several tools change at once —
flagged as a v0 default, not fixed (see Open questions). **Never merges.**

## CLI surface

```
mydocs sync [--repos core,my-guard,...] [--all] [--no-pr]
```

`--all` (default) enumerates every `MyThingsLab` repo with a `CLAUDE.md`;
`--repos` restricts to an explicit list for a targeted re-sync.

## Test plan

- **Happy path:** two fixture repos, one with a changed README hash (no
  prior `kind=docs_sync` entry) and one unchanged (matching hash already on
  record); scripted `Engine` reply for the changed one; assert only the
  changed tool triggers an Engine call, its page lands in the PR, and
  `kind=docs_sync`/`outcome=success` is written for it while the unchanged
  tool gets `outcome=skipped` with **no** Engine call (spy `Engine`).
- **Edge case (nothing stale):** both fixture repos already match their
  recorded hash; assert zero Engine calls and no PR is opened at all.
- **NoopEngine degrade:** assert the published page is the README verbatim
  under templated front matter, and the run still reports `success`.
- Mock only `github.Runner`; hashing and page rendering run against real
  temp fixture repo trees, same style as MyResearcher's tests.

## Dependencies & build order

Depends on core `ledger`, `github` (`list_issues`/`open_pr` — no new core
method needed for v0; repo enumeration goes through raw `gh repo list`, not
a `github.GitHub` method, since that call is org-scoped rather than
repo-scoped like every existing `GitHub` method), `policy`, and `isolation`
(`Workspace`). Independent of MySite (different target repo, different
corpus — fleet READMEs vs. personal-site content — no shared code between
them beyond both using the same PR-opening path every tool already shares).
Depends only on other `My[X]` tools already existing to have something to
document; buildable and testable against fixtures regardless of how many
real tools exist yet. Standalone build, any time after
`mythingslab.github.io`'s genesis content exists for it to write into.

**Open questions:**

- **One PR per run vs. one PR per tool.** v0 batches all stale tools into
  one PR per `sync` run; if that turns out to create awkward, hard-to-review
  PRs once several tools change at once, split to one PR per tool instead —
  not decided here, revisit once real usage shows which is more annoying.
- **Repo-enumeration helper.** `gh repo list MyThingsLab` lives directly in
  `mydocs` for now; promote to a `mythings-core` helper only if a second
  tool independently needs "list every fleet repo" (same premature-
  abstraction discipline the README's cross-cutting notes apply elsewhere).
- **Non-tool pages** (`mythings-core`'s architecture overview,
  `fleet-dispatch`'s own page) are out of scope for MyDocs' per-tool loop;
  whether they're hand-maintained genesis content or a second, smaller sync
  path is deferred until the site's genesis content settles.
