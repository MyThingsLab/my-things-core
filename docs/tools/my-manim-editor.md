---
tool: MyManimEditor
repo: my-manim-editor
package: mymanimeditor
status: designed
added: 2026-07-09
backlog_label: my-manim-editor
engine_call: write one ManimCE Scene subclass for this animation concept
ledger_kinds: [manim_script]
depends_on: []
---

# MyManimEditor — design plan

## Purpose

Given a natural-language animation concept, run **one Engine call** to
translate it into a Manim Community Edition `Scene` subclass — "give it a
concept, get a syntax-valid ManimCE script back." Package `mymanimeditor`,
backlog label `my-manim-editor`.

**v0 scope is deliberately narrower than the idea's own "smallest buildable
slice."** The filed idea (`my-idea#6`) proposed syntax validation *and* a
Manim CLI dry-run/render, with PR automation deferred to v1. This doc goes
further: v0 ships **script generation and syntax validation only** — no
`manim` package, no LaTeX, no FFmpeg dependency anywhere in the tool. Real
rendering is a heavy, flaky CI footprint (LaTeX + FFmpeg + a Manim install)
that isn't warranted for a first ship; it's an explicit v1 open question
below, not built here.

Distinct from its neighbours:

- Unlike MyScraper/MyResearcher, there is no retrieval step — the only input
  is the caller-supplied concept text. No fetching, no corpus, no search.
- Like MyScraper, this is a read-only utility: no `Workspace`, no PR, no
  commit to any repo.

## The single Engine call

One subcommand, one Engine call per run.

### `render`

Required: "write one ManimCE `Scene` subclass for this animation concept,
following ManimCE best practices."

- **Input:** the (length-capped) concept text, and
  `context = {"concept_chars": int, "truncated": bool}`.
- **Output:** `data = {"code": str, "scene_name": str}` — `code` is the full
  Python source of one ManimCE `Scene` subclass; `scene_name` is that class's
  name.
- After the reply, the tool runs stdlib `ast.parse(code)` itself (not the
  Engine) as a syntax gate:
  - Parses clean → `syntax_valid: true`, outcome `success`.
  - Raises `SyntaxError` → `syntax_valid: false`, outcome `failed`, the raw
    parse error is recorded, but the (invalid) script is still returned to
    the caller rather than discarded — same "still return, but flagged"
    posture as MyScraper's `confidence` downgrade rather than a hard skip.
- Against `NoopEngine`: no generation — emits a fixed placeholder `Scene`
  stub as `code`:

  ```python
  from manim import Scene, Write, Text


  class PlaceholderScene(Scene):
      def construct(self):
          self.play(Write(Text("placeholder")))
  ```

  (`scene_name = "PlaceholderScene"`), same honest-degrade posture as
  MyScraper's `fields.raw_text` — no attempt to fake generation without a
  real model behind it.

## Deterministic pre-work

1. Strip the input concept text of leading/trailing whitespace. If it's empty
   after stripping, **skip the Engine call entirely** — outcome `skipped`, no
   script produced. Cheapest possible short-circuit, same posture as
   MyScraper's fetch-failure skip.
2. Cap the concept text length (default 2,000 chars) before it reaches the
   Engine prompt — guards against a pathological/runaway request inflating
   the prompt. `context.truncated=true` if cut, mirroring MyScraper's
   `max_chars` discipline (which caps *output* text; this caps *input* text,
   the same idea applied to the opposite side of the call).
3. No network, no filesystem read beyond the CLI argument itself — the entire
   pre-work step is pure string handling.

## Ledger

- **Writes:** `kind=manim_script`, `outcome=success|failed|skipped`,
  `detail`="generated scene `<scene_name>`" (success), the raw `SyntaxError`
  message (failed), or the skip reason (skipped), `data={concept_chars,
  truncated, scene_name, syntax_valid, comment_url}`.
- **Reads:** none — each run is stateless, no cross-run state.

## Guard & Workspace

**No `Workspace`, no PR.** Read-only utility, same posture as MyScraper: no
repo is ever cloned, edited, or committed to. Output goes to stdout
(`--json`) and/or, if `--issue`, `--repo`, and `--comment` are all given, the
generated code (in a fenced Python code block) is posted as a GitHub issue
comment via `Action(kind="bash", ...)` routed through `Policy.evaluate()`
(default-allow `Policy`, no `MyGuard` dependency needed — same pattern as
MyScraper's `--comment`).

Boundaries:

- No `manim` package, no LaTeX, no FFmpeg — v0 never imports or shells out to
  anything animation-related. The only validation is stdlib `ast.parse`.
- The Engine call is the only judgment step; everything else (length cap,
  empty-input skip, syntax check, comment formatting) is deterministic code,
  no model round-trip.

## CLI surface

```
mymanimeditor render --concept "<text>" [--repo owner/name] [--issue N] [--comment] \
                      [--json] [--engine noop|claude-cli] [--engine-model <model>] \
                      [--ledger <path>] [--max-chars 2000]
```

## Test plan

- **Happy path:** scripted `Engine` reply with valid Scene code; assert
  `ast.parse` succeeds, `outcome=success`, `syntax_valid=true`,
  `kind=manim_script` is written, `--json` prints the record.
- **Edge (syntax error):** scripted `Engine` reply with broken Python (e.g.
  unbalanced parens); assert `ast.parse` raises, `outcome=failed`,
  `syntax_valid=false`, the raw `SyntaxError` text is recorded, and the
  (invalid) script is still returned rather than dropped.
- **Edge (empty concept):** whitespace-only or empty `--concept`; assert the
  Engine is never called (spy `Engine`), `outcome=skipped`.
- **NoopEngine degrade:** assert the fixed `PlaceholderScene` stub is
  returned as `code`, `scene_name="PlaceholderScene"`, `syntax_valid=true`,
  and the run still succeeds.
- **Comment posting:** with `--repo`/`--issue`/`--comment`, assert the
  generated code is posted as a fenced-code-block issue comment via
  `Action(kind="bash", ...)` through `Policy.evaluate()`, matching
  MyScraper's `_comment` wiring.

## Dependencies & build order

Depends on core `ledger` and `policy` only — no `github`/`isolation` needed
beyond the same `github.Runner`-via-`--comment` touchpoint MyScraper already
uses. No new runtime dependency: stdlib `ast` for syntax validation only, no
`manim`/LaTeX/FFmpeg. Standalone; no dependency on any other tool.

**Open questions (deferred to v1):**

- **Real rendering / dry-run.** Actually invoking the `manim` CLI to
  render (or even just `manim --dry_run`/a fast low-quality render) to catch
  runtime errors `ast.parse` can't see (missing imports, wrong constructor
  args, non-existent Mobject methods) is the natural v1 step, but pulls in a
  `manim` package + LaTeX + FFmpeg dependency into the runtime and CI — a
  materially heavier and flakier footprint than the rest of the tool. Not
  decided or built here; v0 ships syntax-validation-only.
- **PR automation.** The filed idea also floated opening a PR with the
  generated `.py` file and a rendered preview. Explicitly out of scope until
  rendering itself exists (a PR with an unrendered, unverified script is low
  value) — v0 stays comment-only, no `Workspace`, no PR, matching MyScraper.
- **Prompt structure for pedagogically-sound scenes.** The Engine call
  optimizes for a *syntactically valid* Scene; whether the animation is
  pedagogically correct or matches the concept's intent is unverified in v0,
  same unresolved-quality posture MyCoder/MyAdvisor already carry — no
  instruction here fixes what `NoopEngine` can't validate.
