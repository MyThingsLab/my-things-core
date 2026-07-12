---
tool: MyEquations
repo: my-equations
package: myequations
status: designed
added: 2026-07-12
backlog_label: my-equations
engine_call: transcribe one detected equation region to LaTeX and explain each symbol from surrounding prose
ledger_kinds: [equation_extract]
depends_on: [tool:my-archivist]
---

# MyEquations — design plan

## Purpose

Extracts every **displayed equation** from a PDF into an indexed form: page
number, a LaTeX transcription, and a symbol-by-symbol explanation grounded
in the surrounding prose (e.g. "here `σ` is the standard deviation of the
noise term, as defined two paragraphs above"). Package `myequations`,
backlog label `my-equations`.

Third of three sibling tools closing the document-structure-extraction gap
— see [the cross-cutting note](README.md) shared with **MyFigure**
([my-figure.md](my-figure.md)) and **MyTables** ([my-tables.md](my-tables.md)).
MyEquations extracts math regions only.

**Structurally different from its two siblings**: MyFigure/MyTables only
call the Engine to fill a caption gap — most of their work is deterministic.
Equations have no deterministic transcription path (there is no
"pdfplumber for math"): classical parsing can *locate* an equation region
reliably, but turning glyph positions into correct LaTeX is exactly the kind
of judgment call the Engine contract exists for. So the one Engine call here
is **required for every detected equation**, not just a caption-gap
fallback — the harness's "exactly one Engine call per run" still holds; a
run over a document with `k` equations is `k` separate tool invocations (or
a batched multi-item Engine call, see below), each one call.

## The single Engine call

Required: "given this equation region (image) and the surrounding page
text, transcribe it to LaTeX and, for each named symbol appearing in it,
give a one-line meaning grounded in the surrounding prose."

- **Input:** the cropped equation region (image, same attachment pattern as
  MyFigure) plus nearby text (for symbol definitions, which conventionally
  appear in the paragraph immediately before or after). `context = {"page":
  n, "nearby_text": "..."}`.
- **Output:** `data = {"latex": str, "symbols": [{"symbol": str, "meaning":
  str}]}`. A symbol whose meaning isn't stated anywhere nearby gets
  `meaning=""` rather than an invented definition — same no-invention
  discipline as MyResearcher's cite-only rule, just for symbol grounding
  instead of citations.
- Against `NoopEngine`: `latex=""`, `symbols=[]` — the equation region is
  still indexed (page, bbox, source image), just untranscribed. A document
  scanned under `NoopEngine` still produces a correct list of *where* the
  equations are, at zero tokens; the transcription is the part that needs a
  real model.
- **Per-document batching**: to keep call count to one-per-*document* rather
  than one-per-equation on documents with many equations, the default mode
  batches all of one document's cropped regions into a single multi-item
  Engine call (`data = {"equations": [{"page", "bbox", "latex", "symbols"},
  ...]}`) — still exactly one call per `myequations extract` invocation, one
  extraction result per document.

## Deterministic pre-work

1. Open the PDF (`PyMuPDF`) and scan each page's text spans for math-typeset
   fonts (CM/CMMI/CMSY/Symbol family names, or an unusually high ratio of
   non-ASCII/math-Unicode codepoints in a short, isolated, often-centered
   line) — this is a **region-detection heuristic**, not a transcription
   attempt; classical parsing never claims to read the equation itself.
2. Cluster adjacent math-flagged spans into bounding boxes (a multi-line
   equation is one region, not one per line) and discard single-character
   hits (an italicized variable inline in prose, e.g. "let `x` be...", is
   not a displayed equation).
3. Crop each surviving region to an image (same crop-and-save mechanism as
   MyFigure) and capture the page text immediately before/after for symbol
   grounding context.
4. Everything from here on is the one batched Engine call above — there is
   no size/quality floor to apply before it, since region detection already
   filtered to "probably math."

## How it's triggered

Same handoff shape as MyFigure/MyTables: MyArchivist files an
`my-equations`-labeled issue (`eq-source:<path>`) per scanned document; this
tool's trigger consumes open `my-equations` issues independently.

## Ledger

- **Writes:** `kind=equation_extract`, `outcome=success|skipped`,
  `detail`="extracted `k` equations from `<doc>`",
  `data={doc_id, equations: [{page, bbox, latex, symbols}]}`.
  `outcome=skipped` when zero math-flagged regions survive clustering.
- **Reads:** nothing — idempotent re-extraction.

## Guard & Workspace

- **`Workspace`**, one PR per source document: adds/updates
  `equations/<doc-id>/` (region crops + `index.json`) and a
  `equations/<doc-id>/README.md` rendering each equation's LaTeX (in a
  fenced ` ```math ` block) with its symbol table beneath. Routed through
  `Policy` (`Guard` default). **Never merges.**

## CLI surface

```
myequations extract <path-or-issue> [--json]
myequations list <doc-id>
```

## Test plan

- **Happy path:** a fixture PDF with one CM-font-typeset displayed equation
  and a symbol defined in the paragraph above; scripted `Engine` returns a
  fixed LaTeX + symbol map; assert the region is detected, cropped, and the
  index matches the scripted output.
- **Inline-variable edge:** a fixture with only an inline italic variable in
  prose (no displayed equation); assert it's filtered at the clustering step
  (single-character/single-line) and never reaches the Engine.
- **Ungrounded-symbol edge:** scripted `Engine` returns a symbol with no
  stated meaning; assert `meaning=""` is preserved rather than backfilled
  with a guess.
- **`NoopEngine`:** regions still indexed with empty `latex`/`symbols`.
- Real fixture PDFs (checked-in minimal binaries built with a CM-family
  font), no mocking of `PyMuPDF` internals.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation.Workspace` (no new
core additions). **Adds `PyMuPDF` as its own runtime dependency** — same
library MyFigure already uses for region cropping, same per-tool placement
rationale (see the cross-cutting note in [README.md](README.md); this is the
clearest case for eventually promoting shared "open PDF, crop region to
image" plumbing once a third real consumer confirms the shape, mirroring how
MyConductor's design doc gated the ordered-selection-helper promotion on its
third caller).

Soft-depends on MyArchivist for the labeled-issue trigger; standalone via
`myequations extract <path>` otherwise. Build after MyFigure if sequencing
by convenience (reuses its image-crop-and-attach Engine-call plumbing
directly) — not hard-blocked.

**Open questions:**

- Font-based region detection is a heuristic, not ground truth: a document
  using an unusual math font family may under-detect, and a document with
  heavy inline-math prose (common in some math-heavy papers) may
  over-cluster short spans into false-positive regions. v0 accepts this and
  reports counts; a human skim of `outcome=success` PRs is the real check
  until real-world false-positive/negative rates are known.
- Whether `latex=""` (untranscribed, `NoopEngine` runs or an Engine
  transcription failure) should still open a PR, or hold back until a real
  Engine backend is configured — v0 opens it either way (consistent with
  MyFigure/MyTables always indexing what's deterministically found); revisit
  if empty-transcription PRs prove noisy in practice.
