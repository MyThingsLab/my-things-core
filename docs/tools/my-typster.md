---
tool: MyTypster
repo: my-typster
package: mytypster
status: shipped
added: 2026-07-08
backlog_label: my-typster
engine_call: draft the Typst source for this content request
ledger_kinds: [typst_doc]
depends_on: []
---

# MyTypster — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-typster's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-typster/README.md`](../../../my-typster/README.md) and
> [`my-typster/CLAUDE.md`](../../../my-typster/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


## Purpose

Given a document-drafting issue labeled `my-typster` (a report, letter,
resume, article, or note, plus a `kind` telling it which template to use),
drafts the content and typesets it as [Typst](https://typst.app) source,
compiles it to a PDF with the real Typst CLI, and opens a PR carrying both
the `.typ` source and the compiled PDF. Package `mytypster`, backlog label
`my-typster`.

MyTypster owns *typesetting* only — turning a content request into
idiomatic, compiling Typst. It deliberately does not own document
*narrative structure* (that's MyPresentation for talks; a future doc for
long-form writing if one is ever proposed) — same "don't conflate a
surface-similar shape" discipline as MySite vs. MyDocs.

## The single Engine call

Required: "given this content request and an existing Typst style anchor,
draft the Typst source."

- **Input:** the issue title + body, plus a deterministically chosen style
  anchor: an existing `templates/<kind>.typ` in the target repo (same
  anchor-file pattern as MySite's page draft). `context = {"issue": N,
  "kind": "resume"|"report"|"letter"|"note"|..., "anchor_path": str}`.
- **Output:** `data = {"typ_source": str}` — one `.typ` file body. The
  model may only use packages already imported by the anchor file (a
  structural fence enforced by the writer, same discipline as MySite's
  path allowlist) — it does not add new Typst package dependencies on its
  own judgment.
- Against `NoopEngine`: degrades to the anchor file's front matter/imports
  unchanged, with the issue body inserted verbatim as the document body —
  honest stub, not fabricated prose, same as MySite's degrade.

## Deterministic pre-work

1. Read the issue (label `my-typster`).
2. Infer `kind` from an issue label or a keyword match against
   `templates/` directory filenames (same naive-tokenizer approach
   MySearcher/MySite use); fall back to `templates/default.typ`.
3. Read the matching template as the style anchor.

## Deterministic post-work (compile gate)

The Engine call produces *source*, not a validated document — Typst has a
real compiler, and an Engine reply can be syntactically wrong in ways
`NoopEngine`'s fixed stub never exercises. So, after the Engine call:

1. Run `typst compile <file>.typ` (the real CLI, never the model) in the
   isolated `Workspace`.
2. **If compilation fails,** do not open a PR — post an issue comment with
   the compiler's error output instead, and stop. This is a
   deterministic short-circuit on the *output* side, mirroring
   MyKnowledger's no-match short-circuit on the *input* side: a run that
   can't produce a valid artifact says so honestly rather than shipping a
   broken PR.
3. If compilation succeeds, both the `.typ` source and the compiled `.pdf`
   go into the PR.

## Ledger

- **Writes:** `kind=typst_doc`, `outcome=success|compile_failed`,
  `detail`="draft for `<slug>` (`kind`)", `data={issue, kind, typ_path,
  pdf_path, pr_url}` on success; `data={issue, kind, typ_path,
  compiler_error}` (no `pdf_path`/`pr_url`) on `compile_failed`.
- **Reads:** nothing — each request is independent, same as MySite.

## Guard & Workspace

One side effect: a **committed PR via `Workspace`** — writes the `.typ`
source and compiled PDF in an isolated worktree, opens a PR carrying
`Closes #N` (same `isolation` + `github.open_pr` path as MySite/MyTester),
each write routed through `Action(kind="fs-write", ...)` → `Policy`,
`ALLOW` by default. **Never merges.**

**First tool needing a compiler-toolchain binary in the CI image**, not
just a Python package — the `typst` CLI itself, alongside the existing
`graphify` CLI dependency already flagged for MyGrapher/MyKnowledger. Pin
a version in the workflow (`typst-community/setup-typst` or a pinned
release download), same "confirm before implementing" discipline as any
new CI dependency.

## CLI surface

```
mytypster draft --issue <number> [--kind resume|report|letter|note|...] \
                [--no-pr]
```

## Test plan

- **Happy path:** a fixture `templates/` dir + fixture issue; scripted
  `Engine` reply with valid `.typ` source; **mock the `typst compile`
  subprocess** (spy) returning success with a fake PDF path; assert the PR
  contains both files and `kind=typst_doc`/`outcome=success` is written.
- **Edge case (compile failure):** mocked `typst compile` returns nonzero
  + stderr; assert no PR is opened, the comment carries the compiler
  error, and `outcome=compile_failed` is written.
- **Structural-fence case:** scripted `Engine` reply that imports a
  package absent from the anchor; assert the writer rejects it before
  even invoking `typst compile` (same "over-scoped reply degrades safely"
  pattern as MySite).
- Mock only `github.Runner` and the `typst` subprocess boundary; template
  selection and file writing run against real temp fixtures, same style
  as MySite's tests.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation` (`Workspace`).
Depends on the `typst` CLI being installed in the CI image (new toolchain
dependency, confirm before implementing). Independent of every other
`My[X]` tool — but **MyPresentation hard-depends on this one** for
compilation, so build MyTypster first.

**Open questions:**

- **PII in a public repo.** Every MyThingsLab repo is public by
  convention (`ARCHITECTURE.md`'s all-public/no-surprise-bill invariant).
  A resume or a personal letter drafted through MyTypster would land in
  that same public repo unless redirected — this is a real conflict, not
  a hypothetical: recommend either a dedicated **private** exception repo
  for personal-document `kind`s (resume/letter), confirmed once before
  building, or restricting MyTypster's default target to non-personal
  document kinds (report/note/article) and handling resumes/letters
  out-of-band. Not decided here.
- **Template repo location.** A dedicated `MyThingsLab/typst-templates`
  repo (shared across every document/presentation kind) vs. templates
  living per-target-repo like MySite's `_pages/` anchors — leaning shared,
  since Typst templates are reusable across many content requests in a
  way Jekyll page anchors aren't, but not decided.
- **Multi-file documents** (a report with chapters as separate `.typ`
  files via `#include`) vs. always single-file — v0 assumes single-file;
  revisit if a real request needs otherwise.
