# MyPresentation — design plan

## Purpose

Given a talk issue labeled `my-presentation` (topic, audience, target
length), drafts a slide-by-slide outline with speaker notes, then hands
that structure to MyTypster to render an actual slide deck (a Typst slide
package, e.g. `touying`/`polylux`, via a `templates/presentation.typ`
anchor) and compile it to PDF. Package `mypresentation`, backlog label
`my-presentation`.

MyPresentation owns the *narrative* — what to say, how to structure a
talk. MyTypster owns *typesetting* — how it's laid out and compiled. This
mirrors MySite vs. MyDocs' "content-publishing, no shared code" split,
except here the two tools have a **real dependency**, not just a
surface-similar shape: MyPresentation's Engine output is deterministic
input to MyTypster's rendering step. See Open questions on how that
dependency should be wired.

## The single Engine call

Required: "given this topic, audience, and target length, draft a
slide-by-slide outline with speaker notes."

- **Input:** the issue title + body (topic, audience, target slide count
  or duration if given). `context = {"issue": N, "target_slides": int |
  None}`.
- **Output:** `data = {"slides": [{"title": str, "bullets": [str],
  "speaker_notes": str}], "est_duration_min": int}`.
- Against `NoopEngine`: one slide titled from the issue, bullets = the
  issue body split into lines, empty speaker notes — honest stub.

## Deterministic pre-work

1. Read the issue (label `my-presentation`).
2. Parse a target slide count or duration from the issue body if given
   (free-text field, same "not a structured field" stance as MySite's
   `kind` inference); default: no cap.
3. **After** the Engine call, if a `target_slides` was given and the
   reply has more slides than that, truncate deterministically (drop
   lowest-priority slides — same size-cap discipline as MyReviewer's diff
   truncation) rather than trusting the model's own count.
4. Hand the (possibly truncated) `slides` structure to MyTypster's
   `presentation` template kind to render `.typ` slide source + compile
   to PDF — this hand-off is deterministic templating (slide → Typst
   slide-package syntax), not a second Engine call.

## Ledger

- **Writes:** `kind=presentation`, `outcome=success|compile_failed`,
  `detail`="deck for `<topic>` (`n` slides)", `data={issue, slide_count,
  typ_path, pdf_path, pr_url}` — `compile_failed` (no `pdf_path`/`pr_url`)
  passes through from MyTypster's own compile-gate outcome unchanged.
- **Reads:** nothing — each request is independent.

## Guard & Workspace

One side effect, delegated to MyTypster's own Workspace/PR path: writes
the compiled deck in an isolated worktree and opens a PR carrying `Closes
#N`. **Never merges.** Plus an issue comment rendering the outline
(title/bullets/speaker notes per slide) so the narrative is reviewable
even before the deck compiles.

## CLI surface

```
mypresentation draft --issue <number> [--slides N] [--no-pr]
```

## Test plan

- **Happy path:** scripted `Engine` slide outline + a **mocked**
  MyTypster compile call; assert the comment renders every slide's
  title/bullets/notes, the PR carries the rendered deck, and
  `kind=presentation`/`outcome=success` is written.
- **Edge case (slide-count overflow):** scripted `Engine` reply exceeds
  `--slides N`; assert deterministic truncation to N slides rather than
  trusting the reply's count, and the dropped slides don't appear in
  either the comment or the deck.
- **Edge case (compile failure):** mocked MyTypster compile step fails;
  assert the outline comment still posts (the narrative review doesn't
  depend on compilation succeeding) but no PR opens and
  `outcome=compile_failed` is written.
- Mock `github.Runner` and the MyTypster compile call; outline rendering
  and slide-count truncation run against real fixtures.

## Dependencies & build order

**Hard-depends on MyTypster** for compilation — build MyTypster first.
Depends on core `ledger`, `github`, `policy`, `isolation` (via MyTypster).
Independent of every other `My[X]` tool.

**Open questions:**

- **How MyPresentation calls MyTypster.** As an installed package
  dependency (like `my-guard` depends on `my-things-core`) vs. shelling
  out to MyTypster's own CLI (`mytypster draft --kind presentation
  --from-json ...`) vs. promoting the render-and-compile step to
  `my-things-core` since it's the second consumer. Leaning toward the CLI
  hand-off — it keeps the two tool repos decoupled at the code level,
  matching the harness's "only shared dependency is core" property — but
  not decided here; confirm before either tool's build starts, per the
  workspace's architectural-change rule.
- **Non-Typst export** (e.g. `.pptx`, which the interactive session
  already has a skill for) as a fallback output format — out of scope for
  v0, Typst/PDF-only.
- **Speaker-notes-only re-runs** (regenerate notes without re-drafting
  slide content) — deferred until there's a real request for it.
