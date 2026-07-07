# MySite — design plan

## Purpose

Given a content or design-change issue (e.g. "add a project page for X",
"write a note on Y", "restyle the projects grid") labeled `my-site` on a
configured Jekyll repo — default `lorenzoliuzzo/lorenzoliuzzo.github.io` —
drafts the page(s), front matter, and navigation entries needed, matching the
site's existing structure and theme conventions, and opens a PR. Package
`mysite`, backlog label `my-site`.

MySite is the fleet's first tool whose **target repo lives outside the
MyThingsLab org** — an existing, generic capability (every tool's target repo
is already configurable at run time per [`ARCHITECTURE.md`](../ARCHITECTURE.md)),
just not exercised until now. It edits *content*, never the Ruby toolchain or
theme choice — a `Gemfile`/`_config.yml` change is a human, out-of-band step.

## The single Engine call

Required: "given this content request and the site's existing structure,
draft the Jekyll content."

- **Input:** the issue title + body, plus deterministically gathered site
  context: the relevant `_data/navigation.yml` section, and one existing page
  of the same kind (a project page if the request is project-shaped, a note
  if note-shaped) as a style anchor. `context = {"issue": N, "kind":
  "project"|"note"|"page", "anchor_path": str}`.
- **Output:** `data = {"files": {path: content}, "nav_patch": [{"section",
  "entry"}]}` — one or more full file bodies (front matter + markdown) and
  the nav entries to add. The model may only write under `_pages/`,
  `_notes/`, or `assets/<kind>/` (an allowlist, not an Engine-trusted claim)
  and may not touch `_config.yml`, `_includes/`, `assets/css/`, or any Ruby
  file — a **structural fence** enforced by the writer (see pre-work),
  the same "may only cite/write within the given scope" discipline every
  other tool's Engine call already holds.
- Against `NoopEngine`: degrades to a single minimal stub page — front
  matter (title from the issue, correct `layout`/`permalink` inferred from
  `kind`) plus the issue body verbatim as placeholder content, and one nav
  entry. Honest degrade, not fabricated prose.

## Deterministic pre-work

1. Read the issue (label `my-site`).
2. Infer `kind` from the issue (a `project`/`note`/`page` label on the issue
   itself, falling back to a keyword match against `_data/navigation.yml`'s
   top-level section names — same naive-tokenizer approach MySearcher uses).
3. Read `_pages/`, `_notes/` (or wherever `kind` resolves), and
   `_data/navigation.yml`; pick one existing entry of the same `kind` as the
   style anchor.
4. Derive the requested slug from the issue title; if a page at that slug
   already exists, **skip the Engine call** and post "a page already exists
   at `<slug>` — close this issue or file a follow-up to edit it instead" —
   MySite drafts new content, it does not silently overwrite existing pages
   (an edit-in-place mode is a possible v1, not decided here — see Open
   questions).

## Ledger

- **Writes:** `kind=site_change`, `outcome=success|skipped`, `detail`="draft
  for `<slug>` (`kind`)", `data={issue, repo, files_written, nav_updated,
  pr_url}`.
- **Reads:** nothing — each request is independent; no cross-run state.

## Guard & Workspace

One side effect: a **committed PR via `Workspace`** — writes the drafted
files plus the nav patch in an isolated worktree and opens a PR carrying
`Closes #N` (the same `isolation` + `github.open_pr` path MyTester/
MyResearcher use), each write routed through `Action(kind="fs-write", ...)` →
`Policy.evaluate()`, `ALLOW` by default (content-only, no deploy, no theme/
config change, no merge). **Never merges** — the site's existing
`.github/workflows/jekyll.yml` builds/deploys once a human merges, same as
today.

## CLI surface

```
mysite draft --issue <number> [--repo lorenzoliuzzo/lorenzoliuzzo.github.io] \
              [--no-pr]
```

## Test plan

- **Happy path:** a fixture site tree (`_pages/`, `_data/navigation.yml`)
  + a fixture issue; scripted `Engine` reply with one new page + a nav
  patch; assert the PR's file set matches, the nav entry lands under the
  right section, and `kind=site_change`/`outcome=success` is written.
- **Edge case (slug collision):** fixture tree already has the requested
  slug; assert the Engine is never called (spy `Engine`), `outcome=skipped`,
  and no PR is opened.
- **Structural-fence case:** scripted `Engine` reply that tries to write
  outside the allowlist (e.g. `_config.yml`); assert the writer drops that
  file, only the allowed files land in the PR, and the run still succeeds
  (an over-scoped Engine reply degrades safely rather than failing the run).
- Mock only `github.Runner`; the front-matter/nav parsing and file rendering
  run against real temp fixture trees, same style as MyResearcher's tests.

## Dependencies & build order

Depends on core `ledger`, `github` (`open_pr` — already exists, no new core
method needed), `policy`, and `isolation` (`Workspace`). No new runtime
dependency — front matter is a thin YAML-header parse (stdlib `yaml` is
already a transitive Jekyll/CI concern, not this tool's; MySite only needs a
YAML *reader*, which `pyyaml` already covers as a common dependency, or a
hand-rolled `---`-delimited splitter if the harness prefers staying
dependency-free — flagged as an open question). Independent of every other
`My[X]` tool; standalone build, any time.

**Open questions:**

- **Hand-rolled front-matter parsing vs. a `pyyaml` dependency.** MySite is
  the first tool that needs to *read and write* YAML front matter rather
  than just consume `mythings-core`'s own YAML-free formats; worth
  confirming whether `pyyaml` is an acceptable new dependency for this one
  tool or whether a minimal `---`-delimited splitter (front matter is
  always flat key/value pairs in this site) is preferred, staying
  dependency-free per the harness's default stance.
- **Edit-in-place mode.** v0 only drafts *new* pages (skip on slug
  collision); whether a second subcommand (`mysite edit --issue N`) should
  update an existing page is deferred until there's a real request for it.
- **Multi-repo config.** v0 defaults to one hard-coded personal site repo
  via `--repo`; whether MySite should ever manage more than one Jekyll site
  is out of scope unless a second one appears.
