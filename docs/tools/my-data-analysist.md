---
tool: MyDataAnalysist
repo: my-data-analysist
package: mydataanalysist
status: building
added: 2026-07-09
backlog_label: my-data-analysist
engine_call: given a deterministic CSV profile, write a short narrative plus one concrete follow-up analysis
ledger_kinds: [analysis]
depends_on: []
---

# MyDataAnalysist — design plan

## Purpose

Given a local CSV file, deterministically **profile** it (schema/type
inference, row count, per-column null counts, basic numeric stats) and run
**one Engine call** to write a short narrative + one concrete follow-up
suggestion — "give it a CSV, get a profile plus a sentence of insight."
Package `mydataanalysist`, backlog label `my-data-analysist`.

Explicitly out of scope for v0: issue-attachment parsing, URLs, remote
datasets — a local file path only (`--file`). No pandas/numpy: this is data
profiling on stdlib `csv`/`statistics`, not heavy numerics, so the harness's
dependency-free-runtime rule holds.

## The single Engine call

One subcommand, one Engine call per run.

### `analyze`

Required: "given this CSV's deterministic profile, write a short narrative
plus one concrete follow-up analysis."

- **Input:** the deterministic profile only — `context = {"file": str,
  "rows": int, "columns": {...}}`, where each `columns[name]` carries its
  inferred type, null count, and (for numeric columns) mean/min/max/stdev.
  No raw row data reaches the Engine, only aggregates.
- **Output:** `data = {"insights": str, "next_analysis": str}` —
  `insights` is a 2-3 sentence narrative, `next_analysis` is exactly one
  suggested follow-up analysis. Both are bounded to a single short string
  each so the call can't sprawl into open-ended exploration.
- Against `NoopEngine`: no insights — `insights` and `next_analysis` are
  empty strings; only the raw profile is returned, same honest-degrade
  posture as MyScraper's `fields.raw_text`.

## Deterministic pre-work

1. Size-cap the input file: 50,000 rows / 10MB. If either is exceeded,
   **skip the Engine call**, outcome `skipped`, and record the reason —
   mirrors MyScraper's fetch-failure skip pattern (deterministic
   short-circuit before any expensive work).
2. Sniff and read the CSV with the stdlib `csv` module (`csv.Sniffer` for
   the dialect, `csv.DictReader` for rows).
3. For each column, infer a type (`int`/`float`/`bool`/`str`) by sampling
   its values — first value that fails a narrower type falls back to the
   next, `str` is the catch-all.
4. Count total rows and, per column, null/empty count.
5. For columns inferred numeric (`int`/`float`), compute mean/min/max/stdev
   over the non-null values (stdlib `statistics`).
6. Assemble the profile (`rows`, `columns` with `type`/`nulls`/stats) and
   pass it to the Engine call, unless step 1's size cap already skipped it.

## Ledger

- **Writes:** `kind=analysis`, `outcome=success|skipped`, `detail`="profiled
  `<file>`" or the skip reason, `data={file, rows, columns, truncated,
  comment_url}`.
- **Reads:** none — each run is stateless and independent, no cross-run
  corpus.

## Guard & Workspace

**No `Workspace`, no PR.** Read-only utility, same posture as MyScraper.
Output goes to stdout (`--json`) and/or, if `--issue`+`--repo`+`--comment`
are given, an issue comment via `Action(kind="bash", ...)` routed through
`Policy.evaluate()` (default-allow `Policy`, no MyGuard dependency needed —
matches MyScraper, not MyTester). Nothing is ever committed to a repo.

Boundaries:

- All profiling is deterministic (no model call) and stdlib-only (`csv`,
  `statistics`) — stays outside the one-Engine-call contract.
- The size cap (50,000 rows / 10MB) is a hard skip, not a truncate-and-
  continue — avoids partial/misleading profiles on oversized input.

## CLI surface

```
mydataanalysist analyze --file <path> [--repo owner/name] [--issue N] \
                         [--comment] [--json] \
                         [--engine noop|claude-cli] [--engine-model ...] \
                         [--ledger path]
```

## Test plan

- **Happy path:** a small fixture CSV (mixed int/float/str/bool columns,
  a few nulls), a scripted `Engine` reply with `insights`/`next_analysis`;
  assert the profile (rows, per-column type/nulls/stats) is computed
  correctly, `outcome=success`, `kind=analysis` is written, `--json` prints
  the record.
- **Edge (size-cap skip):** a fixture file exceeding the row or byte cap;
  assert the Engine is never called (spy `Engine`), `outcome=skipped`, the
  skip reason recorded.
- **NoopEngine degrade:** assert `insights`/`next_analysis` are empty
  strings, the raw profile is still returned, and the run still succeeds.
- Profiling logic (type inference, null counting, stats) runs against real
  fixtures, never mocked — it's pure stdlib, no I/O boundary to mock beyond
  the file read itself.

## Dependencies & build order

Depends on core `ledger` and `policy` only — no `github`/`isolation` needed
since there's no PR path (comment posting reuses `github.Runner` the same
way MyScraper's `--comment` does, but that's the only github touchpoint).
Stdlib-only `csv`/`statistics` — no pandas/numpy, per the harness's
dependency-free-runtime rule. Standalone; no dependency on any other tool.

**Open questions:**

- **Type-inference ambiguity.** Sampling-based inference can misclassify a
  column (e.g. a zip-code column of digit strings inferred as `int`). v0
  accepts this as a known heuristic limitation; a `--schema` override flag
  is a natural v1 addition, not required for v0.
- **JSON/other formats.** v0 is CSV-only, per the filed idea's smallest
  buildable slice. JSON/Parquet input is explicitly deferred.
- **Confirm `kind=analysis`** doesn't collide with an existing ledger
  `kind` before implementation.
