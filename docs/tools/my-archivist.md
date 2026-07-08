# MyArchivist — design plan

## Purpose

Maintains a unified **catalog of a personal book/materials collection** —
physical books on real shelves and digital files (PDF/EPUB) on disk —
as a single, cross-referenced, checked-in index: `catalog/CATALOG.md`
(human-browsable) + `catalog/catalog.json` (the source of truth the
markdown is rendered from). Package `myarchivist`, backlog label
`my-archivist`.

**Not to be confused with MyLibrarian**, despite the name overlap in
English: MyLibrarian recommends *software packages* to depend on
(build-vs-buy over PyPI/npm/GitHub); MyArchivist catalogs a human's *own
books and materials* (title/author/ISBN/shelf/format). Disjoint corpus,
disjoint output, no shared code — same "confirm before folding in" check
noted in MyLibrarian's doc.

MyArchivist is the fleet's **second tool whose target repo/data lives
outside the MyThingsLab org** (after MySite) — the catalog lives in a
personal repo (default configurable, e.g. `lorenzoliuzzo/library`), not a
fleet repo. It is also the **first tool triggered by a local scan/intake
command rather than an opened issue** (a precedent MyNews set for
`schedule:` triggers; MyArchivist's is `myarchivist scan`, run by hand or
on a cron, over local paths + a manually kept intake list, not GitHub
issues at all — see Open questions on whether an issue-driven `add` mode
is worth adding later).

## The single Engine call (optional)

One batched call per run — not one per entry — over every entry still
missing a subject after deterministic lookup; everything else is
deterministic metadata lookup.

"For each numbered book below (title/author), assign one subject/genre tag
and write a one-line blurb" — only entries where deterministic metadata
(see pre-work) didn't already carry a subject/genre are sent; if none are
pending, the Engine call is skipped entirely (same short-circuit as
MyResearcher's `plan` mode with under 2 topics).

- **Input:** the pending entries as a numbered list (`id`, `title`,
  `author`). `context = {"pending_count": k}`.
- **Output:** `data = {"tags": [{"id": int, "tag": str, "blurb": str}, ...]}`
  — one tag from a small fixed vocabulary
  (fiction/non-fiction/technical/reference/other, same closed-set discipline
  as MyGroomer's labels) plus a one-line blurb per entry, referencing only
  the given numeric `id`s — never an invented one (same permutation-only
  discipline as MySearcher's reorder rule). The model may not invent
  bibliographic facts (title/author/ISBN are already fixed by deterministic
  lookup, never Engine-supplied).
- Against `NoopEngine`: `tag="unsorted"`, no blurb — the entry still gets
  cataloged, just without enrichment, same honest degrade as every other
  tool's `NoopEngine` path.

## Deterministic pre-work

1. **Digital scan** (`--digital <dir>`, repeatable): walk the directory for
   `.pdf`/`.epub` files. Extract embedded metadata (PDF `/Info` dict via
   stdlib-adjacent parsing already vendored for MyTypster's PDF output path
   if reusable, else a minimal hand-rolled reader; EPUB's `content.opf` via
   stdlib `zipfile` + `xml.etree`, both already-used stdlib per the
   dependency-free rule). Falls back to filename-derived title/author
   (`Author - Title.pdf`) when embedded metadata is absent.
2. **Physical intake** (`--physical <intake.csv>`): a small manually kept
   CSV (`isbn,shelf` or `title,author,shelf` for the rare pre-ISBN book) —
   MyArchivist never invents a physical inventory; a human owns what's on
   the shelf.
3. **ISBN enrichment** for any entry with an ISBN and missing metadata:
   **Open Library API** (`openlibrary.org/api/books`, **no key**) over
   stdlib `urllib` — canonical title/author/subjects/cover, same
   LLM-free-HTTP discipline as MyResearcher/MyLibrarian.
4. **Dedupe + cross-reference**: match by ISBN first, else normalized
   title+author (same naive-tokenizer normalization MySearcher/MyResearcher
   use). A title held in both formats becomes **one** catalog entry with
   `formats: ["physical", "digital"]`, not two — this is the tool's core
   value over a flat file listing.
5. If Open Library returns nothing and no digital metadata carries a
   subject, the entry proceeds to the Engine step (see above) rather than
   blocking the run — a missing subject is not a fatal condition.

## Ledger

- **Writes:** `kind=catalog`, `outcome=success|skipped`, `detail`="`k` new
  entries (`d` digital, `p` physical)", `data={new_entries, deduped,
  enriched, catalog_path, pr_url}`.
- **Reads:** the existing `catalog/catalog.json` (to diff against for
  idempotency — a re-scan with no new files/intake rows is `outcome=skipped`,
  no empty PR, same discipline as MyResearcher/MyTodo).

## Guard & Workspace

Writes `catalog/CATALOG.md` + `catalog/catalog.json` inside an
`isolation.Workspace` worktree and opens exactly one PR per run (or resumes
the run's existing branch on a re-run before merge, same idempotency
pattern as MyTester/MyChangelogger). `Action(kind="bash", ...)` routed
through `Policy`, `ALLOW` by default — a non-destructive doc/data PR, never
a merge. No issue comment (there is no triggering issue in the common
path); an optional `--issue N` lets a human request a catalog refresh via
the usual issue-driven path for consistency with the rest of the fleet, in
which case it also comments on that issue.

## CLI surface

```
myarchivist scan [--digital <dir> ...] [--physical <intake.csv>] \
                 [--repo owner/name] [--issue N] [--no-pr] \
                 [--engine claude-cli]
```

## Test plan

- **Happy path:** a fixture digital dir (2-3 files with embedded metadata)
  + a fixture intake CSV (2-3 ISBNs); **mocked** Open Library HTTP; assert
  `catalog.json`/`CATALOG.md` render the merged, cross-referenced entries
  and a PR is opened (fake `github.Runner`), `kind=catalog`/`outcome=success`.
- **Dedupe:** a fixture where the same ISBN appears in both the digital scan
  (embedded metadata) and the physical intake CSV; assert exactly one entry
  with `formats: ["physical", "digital"]`.
- **Idempotent re-run:** run twice with no new inputs; assert the second run
  is `outcome=skipped` and no second PR opens.
- **`NoopEngine` degrade:** an entry with no subject from any deterministic
  source; assert it's cataloged with `tag="unsorted"` and no fabricated
  blurb, and the run still succeeds.
- **Metadata-extraction edge:** a PDF/EPUB with no embedded metadata; assert
  the filename-derived fallback populates `title`/`author` rather than
  failing the scan.
- Mock the HTTP boundary (Open Library) and `github.Runner`; the
  file-parsing (PDF/EPUB) and dedupe logic run against real fixture files,
  never mocked. One live-network smoke test is `@pytest.mark.slow`.

## Not in scope (v0)

Lending/checkout tracking (who has which physical copy); cover-image
storage (link to Open Library's cover URL, don't vendor images into the
repo); full-text search over digital files (a MyGrapher/graphify concern
if it comes up, not this tool's job); barcode-scanner integration (the
physical intake path is a CSV a human fills in, by hand or from whatever
scanner app they already use — no new hardware integration here).

## Dependencies & build order

Depends on core `ledger`, `policy`, `isolation` (`Workspace` for the PR
path); `github` only for the optional `--issue` comment path. The
ISBN-lookup layer is **stdlib-only** (`urllib` + `json`), same posture as
MyResearcher/MyLibrarian. PDF/EPUB metadata extraction is a new,
self-contained parsing concern with no other tool depending on it —
independent of every other tool; no ordering dependency, though it shares
enough retrieval-layer shape with MyResearcher/MyLibrarian that building it
after either means less code duplicated from scratch.

**Open questions:**

- **Default target repo.** MySite's precedent is a configurable personal
  repo, no fleet-wide default; same here — pick the destination
  (`lorenzoliuzzo/library` or similar) when implementation starts, not
  decided in this doc.
- **Is an issue-driven `add <isbn>` mode worth it?** The scan/intake path
  covers bulk cataloging; a one-off "add this single book" issue (label
  `my-archivist`) would fit the fleet's usual pattern better than editing
  the intake CSV by hand for a single row. Not decided — start with `scan`,
  add `add` if the CSV-editing friction shows up in practice.
- **PDF metadata parsing library.** No vendored PDF-metadata reader exists
  in the fleet yet; check whether MyTypster's PDF-output path already
  carries a usable stdlib-only reader before writing a new one from
  scratch, or whether MyLibrarian (once built) turns up an existing
  MIT-licensed package worth taking a runtime dependency on instead of
  hand-rolling — a natural first real-world MyLibrarian consumer.
