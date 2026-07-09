---
tool: MyNotes
repo: my-notes
package: mynotes
status: designed
added: 2026-07-09
backlog_label: my-notes
engine_call: extract 3-7 tags/topics and propose a title for this note
ledger_kinds: [note_tagged]
depends_on: []
---

# MyNotes — design plan

## Purpose

A personal freeform note-capture tool. A note is filed as a GitHub issue
(mirroring MyIdea's issue-driven pattern); MyNotes reads the issue body, runs
**one Engine call** to extract tags/topics and propose a concise title, and
comments the structured result back on the issue. Package `mynotes`, backlog
label `my-notes`.

Distinct from its neighbours:

- **MyIdea** files unstructured input as issues and uses the Engine to
  organize/structure results too, but explores a **tool idea** against the
  fleet (overlaps, contract fit, verdict) — a different corpus and a
  different judgment question than tagging a personal note.
- **MyWiki** answers "what happened / why" from *this project's own* ledger
  history — a query tool over structured runtime history, not a capture tool
  for freeform personal notes.
- **MyKnowledger** answers domain questions from a pre-built external
  literature corpus — MyNotes never builds or reads a corpus; each run is one
  issue, comment-only.

Explicitly out of scope for v0: cross-linking between notes, a storage
backend/persistence beyond the issue comment itself, deduplication against
MyIdea/MyWiki. See "Open questions" below for what's deferred, not decided.

**Overlaps:** MyIdea's own idea-exploration brief (issue #9, filed against
`my-idea`) already flagged this: "Both file unstructured input as issues and
use Engine to organize/structure results, but serve different purposes (tool
ideas vs personal notes) and have different organizational strategies."
Verdict there was `build`, with the smallest buildable slice being exactly
this v0: "Accept a note as an issue with a `my-notes` label; run Engine to
extract tags/topics; comment back with structured tags. Skip cross-linking,
storage PR, and deduplication for v0." That exploration also flagged an open
question about a relationship to a not-yet-built MyWiki — deferred here, not
resolved, per the decision below.

## The single Engine call

One subcommand, one Engine call per run.

### `tag`

Required: "extract 3-7 tags/topics and propose one concise title for this
note."

- **Input:** the (capped) note text plus `context = {"note_chars": int,
  "truncated": bool}`.
- **Output:** `data = {"title": str, "tags": [str]}` — tags bound to a max of
  7, deduped.
- Against `NoopEngine`: `tags = []`, `title` falls back to the first
  non-empty line of the note text (truncated to ~60 chars) — deterministic,
  no Engine needed for this degrade path, the same honest-degrade posture as
  MyScraper's raw-text fallback and MyIdea's grounding-only brief.

## Deterministic pre-work

1. Fetch the issue body via the `mythings.github.GitHub`/`Runner` seam (same
   boundary MyIdea reads a filed idea's body through) — no new dependency,
   no model call.
2. Size-cap the note text (default 10,000 chars) before it reaches the Engine
   prompt — the same size-cap discipline as every retrieval/capture tool in
   the line; `context.truncated = true` if cut.
3. If the body is empty after stripping whitespace, **skip the Engine call**
   entirely, outcome `skipped` — deterministic short-circuit, same posture as
   MyScraper's "empty stripped text" skip.

## Ledger

- **Writes:** `kind=note_tagged`, `outcome=success|skipped`, `detail`="tagged
  issue #`<n>` with `<k>` tags" or the skip reason, `data={issue, repo,
  note_chars, truncated, title, tags, comment_url}`.
- **Reads:** none — each run is stateless and independent, no cross-run
  corpus (same posture as MyScraper).

## Guard & Workspace

**No `Workspace`, no PR.** Read-only utility — like MyScraper, not like
MyTester/MyCoder. This tool has **no local-file mode**: it always requires
`--issue` + `--repo`, since the issue *is* the input (unlike MyScraper, which
takes a URL). Output goes to stdout (`--json`) and, when `--comment` is
passed, an issue comment via `Action(kind="bash", ...)` routed through
`Policy.evaluate()` (default-allow `Policy`, no MyGuard dependency needed).
`--json`/stdout is always available for a dry look without posting.

Boundaries:

- Comment-only side effect, through `Policy` — never files issues, never
  opens a PR, never edits the source issue.
- Stateless: no cross-run corpus, no persistence beyond the one issue
  comment per run.

## CLI surface

```
mynotes tag --repo owner/name --issue N [--comment] [--json] \
            [--engine noop|claude-cli] [--engine-model ...] \
            [--ledger path] [--max-chars 10000]
```

## Test plan

- **Happy path:** a fixture issue body (mocked `gh`/Runner boundary, same
  style as MyIdea's `FakeGh`), a scripted `Engine` reply with `tags`+`title`;
  assert `outcome=success`, `kind=note_tagged` is written, tags bound/deduped
  to max 7, `--json` prints the record, `--comment` posts through `Policy`.
- **Edge (empty body):** issue body empty/whitespace-only; assert the Engine
  is never called (spy `Engine`), `outcome=skipped`, skip reason recorded.
- **NoopEngine degrade:** assert `tags=[]` and `title` falls back to the
  first non-empty line of the note (truncated to ~60 chars), deterministically,
  no Engine call needed for the fallback itself.
- Mock the `gh`/Runner boundary exactly like MyIdea's tests do (`FakeGh`
  pattern) — never mock internal logic.

## Dependencies & build order

Depends on `my-things-core` only — needs the `github`/`Runner` seam for
reading the issue body and posting the comment, the same boundary MyIdea
already uses. No `Workspace`, no `isolation` dependency (no PR path). No
dependency on any other `My[X]` tool; standalone.

**Open questions (deferred, not blockers for v0):**

- **Storage backend relationship to MyWiki.** Whether MyNotes should ever
  share a persistence layer with a future MyWiki (or a not-yet-built
  MyWiki-adjacent notes store) is explicitly undecided — v0 ships fully
  standalone, comment-only, no shared backend.
- **Note mutability.** Immutable (new versions filed as separate issues) vs.
  editable (updates reflected in place) is unresolved; v0 has no update path
  at all, so the question doesn't yet bite.
- **Archival/decay strategy.** Whether old notes ever get archived or expire
  is undecided; v0 keeps every note as a permanent, unmanaged GitHub issue.
- **Vocabulary tuning.** Whether the Engine's tagging can be tuned to a
  user's own recurring vocabulary/topics over time, or stays generic, is
  deferred until there's a real Engine backend and enough tagged notes to
  judge against.
