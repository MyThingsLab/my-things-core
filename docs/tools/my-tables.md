---
tool: MyTables
repo: my-tables
package: mytables
status: designed
added: 2026-07-12
backlog_label: my-tables
engine_call: match each detected table region to its nearest caption text and summarize what the table reports
ledger_kinds: [table_extract]
depends_on: [tool:my-archivist]
---

# MyTables — design plan

## Purpose

Extracts every **table** from a PDF into structured form — page number, the
table's cells (as CSV + a rendered Markdown table), its caption
(deterministically located), and a one-line Engine-written summary of what
the table reports. Package `mytables`, backlog label `my-tables`.

Second of three sibling tools closing the document-structure-extraction gap
— see [the cross-cutting note](README.md) shared with **MyFigure**
([my-figure.md](my-figure.md)) and **MyEquations**
([my-equations.md](my-equations.md)). MyTables extracts tabular regions
only; it never touches images or math.

## The single Engine call

Required only when a table's caption is missing or generic: "given this
table's cells and the surrounding page text, write a one-line summary of
what the table reports."

- **Input:** the table's cells (as a small CSV, not an image — table
  structure is already deterministic by the time the Engine sees it) plus
  the page's plain text for context. `context = {"page": n, "nearby_text":
  "..."}`.
- **Output:** `data = {"summary": str}` — one line, grounded only in the
  cell contents and stated page text; the Engine never invents cell values.
- Against `NoopEngine`: `summary=""`; the table is still indexed with its
  cells and any deterministically-found caption.

## Deterministic pre-work

1. Open the PDF (`pdfplumber`, which layers table detection on top of
   `pdfminer.six`'s text/line geometry) and run its per-page
   `page.extract_tables()` to get cell grids with bounding boxes.
2. Discard degenerate results — a single row or single column is usually a
   text-layout artifact, not a table; a fixed minimum-rows×columns floor
   filters these before anything reaches the Engine.
3. For each surviving table, look for a caption the same way MyFigure does:
   a line matching `^(Table\s*\d+)` within a fixed vertical distance of the
   table's bounding box (checked above first — table captions conventionally
   sit above, unlike figure captions below).
4. Write `tables/<doc-id>/p<page>-<n>.csv` plus
   `tables/<doc-id>/index.json` (page, bbox, caption, summary, source file)
   inside the `Workspace`.
5. Only tables with no usable caption reach the Engine call.

## How it's triggered

Same handoff shape as MyFigure: MyArchivist's existing catalog scan files a
`my-tables`-labeled issue (`table-source:<path>`) per scanned document that
doesn't have one yet; MyTables' own trigger consumes open `my-tables`
issues. No import or direct call between the two tools.

## Ledger

- **Writes:** `kind=table_extract`, `outcome=success|skipped`,
  `detail`="extracted `k` tables from `<doc>`",
  `data={doc_id, tables: [{page, bbox, caption, summary, rows, cols}]}`.
  `outcome=skipped` when zero tables survive the row/column floor.
- **Reads:** nothing — idempotent re-extraction from the source PDF.

## Guard & Workspace

- **`Workspace`**, one PR per source document: adds/updates
  `tables/<doc-id>/` (CSVs + `index.json`) and a
  `tables/<doc-id>/README.md` rendering each table as Markdown with its
  caption/summary above it. Routed through `Policy` (`Guard` default).
  **Never merges.**

## CLI surface

```
mytables extract <path-or-issue> [--min-rows n] [--min-cols n] [--json]
mytables list <doc-id>
```

## Test plan

- **Happy path:** a fixture PDF with one clean grid table + adjacent "Table
  1: ..." caption above it; assert deterministic caption match, no Engine
  call, correct CSV + index.
- **Missing-caption edge:** same fixture, caption stripped; assert exactly
  one Engine call and its `summary` lands in the index.
- **Degenerate-table edge:** a fixture whose only "table-shaped" region is a
  single-column bullet list; assert it's filtered pre-Engine and
  `outcome=skipped`.
- **`NoopEngine`:** summary empty, cells/caption still indexed.
- Real fixture PDFs, no mocking of `pdfplumber` internals.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`, `isolation.Workspace` (no new
core additions). **Adds `pdfplumber` as its own runtime dependency** in
`my-tables`'s `pyproject.toml`, not core's — same per-tool placement
rationale as MyFigure's `PyMuPDF`; see the cross-cutting note in
[README.md](README.md).

Soft-depends on MyArchivist for the labeled-issue trigger; standalone via
`mytables extract <path>` otherwise. Independent of MyFigure/MyEquations —
build in any order, though all three sharing the "open a PDF, filter
detected regions, caption-match, Engine-fill-gaps" shape means building the
first one first and copying its test-fixture harness is the fast path for
the other two.

**Open questions:**

- `camelot-py` (Ghostscript-backed) generally out-detects `pdfplumber` on
  borderless/whitespace-delimited tables but adds a system-binary dependency
  (Ghostscript) beyond what CI images currently have — v0 ships with
  `pdfplumber` only; revisit if borderless tables prove common in real
  usage.
- Multi-page tables (a table that continues onto the next page with no
  repeated header) — v0 indexes each page's table independently; stitching
  is deferred, same as MyFigure's wraparound-figure gap.
