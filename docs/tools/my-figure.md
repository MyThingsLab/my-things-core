---
tool: MyFigure
repo: my-figure
package: myfigure
status: building
added: 2026-07-12
backlog_label: my-figure
engine_call: match each detected image region to its nearest caption text and write a one-line description
ledger_kinds: [figure_extract]
depends_on: [tool:my-archivist]
---

# MyFigure — design plan

## Purpose

Extracts every embedded **figure** (raster/vector image region) from a PDF
into a cross-referenced index: page number, the image itself (saved
alongside), its caption text (deterministically located, not invented), and
a one-line Engine-written description for figures whose caption is missing
or unhelpful. Package `myfigure`, backlog label `my-figure`.

First of three sibling tools closing the same gap — see
[the cross-cutting note on document-structure extraction](README.md) shared
with **MyTables** ([my-tables.md](my-tables.md)) and **MyEquations**
([my-equations.md](my-equations.md)). Distinct from its neighbours: MyFigure
extracts raster/vector image regions; MyTables extracts tabular regions;
MyEquations extracts math regions. None of the three touches the other two's
region type, and a document with no matches for a tool is a clean
`outcome=skipped`, not an error.

Not **my-image-processor** (which processes a given image file — EXIF,
resize, format — and never opens a PDF or knows what a "figure" is).

## The single Engine call

Required only for figures whose deterministically-located caption is
missing, truncated, or generic (e.g. "Figure 3" with no further text):
"given this image and the surrounding page text, write a one-line
description of what the figure shows."

- **Input:** the extracted image, as a PNG-encoded `EngineRequest.images`
  entry (core#111's addition — `ClaudeCLIEngine` sends it over the CLI's
  stream-json wire format, the one path that actually attaches an image;
  MyImageProcessor's own Engine call is text-only and doesn't apply here),
  plus the page's plain text for context. `context = {"page": n,
  "nearby_text": "..."}`.
- **Output:** `data = {"description": str}` — one line, no invention beyond
  what's visible in the image and stated on the page.
- Against `NoopEngine`: `description=""`; the figure is still indexed with
  its page, bounding box, and any deterministically-found caption — the
  Engine call only fills a gap, it never gates whether a figure gets
  indexed.

## Deterministic pre-work

1. Open the PDF (`PyMuPDF`/`fitz`) and enumerate embedded image XObjects per
   page — position (bounding box), size, and the raw image bytes
   (`page.get_images()` + `page.get_image_rects()`).
2. Discard images below a size/area floor (default: smaller than roughly a
   text glyph — logos, bullet icons, watermarks) — a filter, not a
   classifier; no Engine call decides what counts as a figure.
3. For each surviving image, look for a caption by regex over nearby text
   blocks: a line matching `^(Fig(ure)?\.?\s*\d+)` within a fixed vertical
   distance below (or, failing that, above) the image's bounding box.
4. Save each image to `figures/<doc-id>/p<page>-<n>.png` inside the
   `Workspace`, alongside `figures/<doc-id>/index.json` (page, bbox, caption,
   description, source file).
5. Only figures with no usable caption reach the one Engine call (step
   above); this keeps the call count to "however many figures actually need
   help," not one-per-figure unconditionally — same discipline as
   MyArchivist's "only entries needing enrichment" gate.

## How it's triggered

Mirrors MyArchivist's existing `my-bibliography`-labeled-issue handoff
([my-archivist.md](my-archivist.md)): MyArchivist's catalog scan already
walks the same PDF/EPUB collection for metadata. When a scanned PDF has no
`my-figure`-labeled issue open or closed against it yet, MyArchivist files
one (`fig-source:<path>`), and MyFigure's own trigger (`schedule:` or a
manual `myfigure extract <path>`) picks up open `my-figure` issues the same
way MyBibliography already does for `isbn:` issues. MyArchivist never opens
the PDF itself or calls this tool directly — same "labeled issue, not an
import" boundary the fleet already uses.

## Ledger

- **Writes:** `kind=figure_extract`, `outcome=success|skipped`,
  `detail`="extracted `k` figures from `<doc>`",
  `data={doc_id, figures: [{page, bbox, caption, description}]}`.
  `outcome=skipped` when zero figures survive the size floor — a text-only
  PDF is not an error.
- **Reads:** nothing — re-running on the same PDF re-extracts from scratch
  (idempotent by construction: same input bytes, same output index).

## Guard & Workspace

- **`Workspace`**, one PR per source document: adds/updates
  `figures/<doc-id>/` (images + `index.json`) and a short
  `figures/<doc-id>/README.md` table (page, thumbnail link, caption).
  Routed through `Policy` (`Guard` default). **Never merges.**

## CLI surface

```
myfigure extract <path-or-issue> [--min-area px2] [--json]
myfigure list <doc-id>              # print the index for an already-run doc
```

## Test plan

- **Happy path:** a fixture PDF (built with `reportlab` or a checked-in
  minimal binary) with one image + adjacent "Figure 1: ..." caption; assert
  the caption is found deterministically, no Engine call fires, and
  `figures/<doc-id>/index.json` is written correctly.
- **Missing-caption edge:** same fixture with the caption line removed;
  assert exactly one Engine call fires and its `description` lands in the
  index.
- **Size-floor edge:** a fixture with a small logo image; assert it's
  filtered before any Engine call, and `outcome=skipped` when it's the only
  image.
- **`NoopEngine`:** description empty, everything else still indexed.
- PDF fixtures are real files (small, checked in or generated at test time)
  — no mocking of `PyMuPDF`'s internals, matching the fleet's "don't mock
  what you can construct for real" posture for file-format boundaries.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation.Workspace` (no new
core additions). **Adds `PyMuPDF` (`pymupdf`) as its own runtime dependency**
in `my-figure`'s `pyproject.toml` — not core's, which stays dependency-free
per `my-things-core/CLAUDE.md`; mirrors MyImageProcessor's own Pillow
dependency. See the cross-cutting note in [README.md](README.md) for why
this library lives per-tool rather than in `mythings.corpus`, and for the
now-three-way duplication of "open this PDF" across MyFigure/MyTables/
MyEquations that a future promotion could collapse.

Soft-depends on MyArchivist for the labeled-issue trigger (build order
doesn't block: `myfigure extract <path>` works standalone against any local
PDF without MyArchivist ever running).

**Open questions:**

- Vector-drawn figures (a chart built from PDF path operators, not an
  embedded raster) are invisible to `page.get_images()` — v0 only catches
  raster/embedded-image figures; vector figures are a known gap, not
  silently mis-detected as something else.
- Multi-page or wraparound figures (a diagram split across a page break) —
  v0 indexes each page's regions independently; stitching is deferred.
