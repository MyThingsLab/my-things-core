---
tool: MyImageProcessor
repo: my-image-processor
package: myimageprocessor
status: designed
added: 2026-07-09
backlog_label: my-image-processor
engine_call: interpret this deterministic image profile and suggest one concrete follow-up processing step
ledger_kinds: [image_analysis]
depends_on: []
---

# MyImageProcessor — design plan

## Purpose

Given a local image file, deterministically extract dimensions, format, a
color histogram summary, and EXIF metadata, then run **one Engine call** to
interpret the findings and suggest one concrete follow-up processing step.
Package `myimageprocessor`, backlog label `my-image-processor`.

Mirrors MySignalProcessor's architecture but operates on image data instead
of signal data: deterministic feature extraction, one bounded Engine call for
judgment, no `Workspace`, no PR — a read-only analysis utility.

Explicitly out of scope for v0: issue-attachment sourcing, URL sourcing,
batch mode, and "basic CV features" beyond a coarse color histogram (edge/
corner/blob detection, object recognition). One local file in, one profile +
interpretation out.

## The single Engine call

One subcommand, one Engine call per run.

### `analyze`

Required: "given this deterministic image profile, interpret the findings in
2-3 sentences and suggest exactly one concrete follow-up processing step."

- **Input:** `context = {"file": str, "width": int, "height": int, "format":
  str, "histogram_summary": {...}, "exif": {...}}`. `exif` never carries raw
  GPS coordinates — only `has_gps: bool` (see Risks/Privacy below).
- **Output:** `data = {"interpretation": str, "suggested_step": str}`.
- Against `NoopEngine`: no interpretation — `interpretation` and
  `suggested_step` are both empty strings; only the raw deterministic profile
  is returned, same honest degrade as MyScraper/MyResearcher.

## Deterministic pre-work

1. Open the file with `PIL.Image` (Pillow). If it can't be opened or decoded
   (corrupt file, unsupported format), **skip the Engine call**, outcome
   `skipped`, record the reason — same short-circuit discipline as
   MyScraper's fetch-failure path.
2. Read `width`, `height`, `format`, `mode` from the opened image.
3. Compute a coarse color histogram summary — mean and standard deviation per
   RGB channel (converting to `RGB` mode first if needed). Deliberately
   small and fixed-size so it can never blow the Engine's context budget,
   unlike a full per-bucket histogram dump.
4. Extract EXIF tags via `PIL.ExifTags` if present: camera model, timestamp.
   GPS presence is recorded as `has_gps: bool` only — **raw GPS coordinates
   are never read into the profile passed to the Engine prompt or written to
   the ledger.** This is a privacy-sensitive field the idea's own risk list
   flagged explicitly.
5. If any of the above raises (corrupt/malformed EXIF, truncated image data),
   treat it the same as an open failure: skip the Engine call, outcome
   `skipped`.

## Ledger

- **Writes:** `kind=image_analysis`, `outcome=success|skipped`, `detail`=
  "analyzed `<file>` (`<w>`x`<h>` `<format>`)" or the skip reason,
  `data={file, width, height, format, has_exif, has_gps, comment_url}`.
  Never persists raw GPS coordinates or the full EXIF blob — only the
  derived summary fields above.
- **Reads:** none — each run is stateless, one file per invocation, no
  cross-run corpus.

## Guard & Workspace

**No `Workspace`, no PR.** Read-only utility, same posture as MyScraper.
Output goes to stdout (`--json`) and/or, if `--issue`+`--repo`+`--comment`
are given, an issue comment via `Action(kind="bash", ...)` routed through
`Policy.evaluate()` (default-allow `Policy`, no MyGuard dependency needed).
Nothing is ever committed to a repo.

Boundaries:

- All image decoding is deterministic (Pillow, no model call) — stays
  outside the one-Engine-call contract, same posture as MyScraper's HTTP
  layer.
- **Privacy discipline:** raw GPS coordinates from EXIF never reach the
  Engine prompt and are never written to the ledger — only `has_gps: bool`.
  This is the tool's one hard invariant, not a style preference.
- v0 accepts a local file path only (`--file`); no issue attachments, no
  URLs, no batch mode — all explicitly deferred per the idea's smallest-
  buildable-slice call.

## CLI surface

```
myimageprocessor analyze --file <path> [--repo owner/name] [--issue N] [--comment] \
                          [--json] [--engine noop|claude-cli] [--engine-model ...] \
                          [--ledger path]
```

## Test plan

- **Happy path:** a small generated fixture image (built with Pillow in the
  test itself), a scripted `Engine` reply with `interpretation`/
  `suggested_step`; assert `outcome=success`, `kind=image_analysis` is
  written, `--json` prints the profile + interpretation.
- **Edge (corrupt file):** a fixture file that isn't a valid image (or is
  truncated); assert the Engine is never called (spy `Engine`),
  `outcome=skipped`, failure reason recorded.
- **Edge (EXIF with GPS):** a fixture image with EXIF GPS tags; assert the
  Engine request's `context["exif"]` contains `has_gps: true` and **no** raw
  coordinate fields, and that the ledger entry's `data` also carries no raw
  coordinates or full EXIF blob.
- **NoopEngine degrade:** assert `interpretation`/`suggested_step` are empty
  strings and the raw profile is still returned, run still succeeds.
- Pillow is a real dependency exercised directly (not mocked) — fixture
  images are generated in-test; only the `Engine`/`gh` boundaries are mocked.

## Dependencies & build order

Depends on core `ledger` and `policy` only — no `github`/`isolation` beyond
the same optional `--comment` posting MyScraper uses. Adds **Pillow>=10** as
a runtime dependency for image decoding/EXIF — a non-SDK compute/decode
library, matching the `my-raytracer` precedent (`numpy`) within the harness's
"dependency-free runtime" rule (which targets API SDKs, not decode/compute
libraries). Standalone; no dependency on any other tool. Mirrors
MySignalProcessor's shape (a sibling tool being built in parallel) but the
two share no code or dependency — one processes images, the other signals.

**Open questions:**

- **Issue-attachment and URL sourcing.** Deferred per the idea's smallest-
  buildable-slice call; a natural v1 addition once a local-file v0 ships.
- **Coarser vs. finer histogram detail.** v0 uses mean/std per RGB channel.
  A quantized N-bucket histogram is a possible v1 enrichment if the Engine's
  interpretations prove too coarse in practice — not decided here.
- **Confirm `kind=image_analysis`** doesn't collide with an existing ledger
  `kind` before implementation.
