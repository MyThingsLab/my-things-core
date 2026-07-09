---
tool: MySignalProcessor
repo: my-signal-processor
package: mysignalprocessor
status: designed
added: 2026-07-09
backlog_label: my-signal-processor
engine_call: narrate FFT/stat findings and suggest one concrete follow-up action
ledger_kinds: [signal_analysis]
depends_on: []
---

# MySignalProcessor — design plan

## Purpose

Given a local CSV time-series file, compute an FFT power spectrum and basic
statistics **deterministically**, then run **one Engine call** to narrate the
findings and suggest one concrete follow-up action — "give it a signal, get a
plain-language read on it back." Package `mysignalprocessor`, backlog label
`my-signal-processor`.

Distinct from its neighbours: nothing else in the fleet touches numeric
signal data — MySearcher/MyKnowledger/MyScraper all operate on text/files as
prose, not as a value series to transform mathematically. This is the first
tool with a compute dependency (`numpy`) rather than an API SDK.

Explicitly out of scope for v0: issue attachments, URLs, or any input source
other than a local CSV path; timestamp-column parsing (sample rate is a flag,
not inferred); filtering/windowing/decimation; frequency-domain plots. One
CSV in, one narrated record out.

## The single Engine call

One subcommand, one Engine call per run.

### `analyze`

Required: "given these deterministic FFT/statistics results, narrate the
findings and suggest one concrete follow-up action."

- **Input:** `context = {"file": str, "n_samples": int, "sample_rate": float,
  "dominant_freq_hz": float, "mean": float, "std": float, "peak": float}` —
  the deterministic pre-work's output, no raw samples in the prompt.
- **Output:** `data = {"narrative": str, "suggested_action": str}` —
  `narrative` is 2-3 sentences describing what the stats show;exactly **one**
  concrete follow-up action, phrased **tool-agnostic** (never names another
  My[X] tool by name — this was an explicit open question in the idea
  exploration, resolved this way so the tool doesn't hard-couple its output
  to fleet composition).
- Against `NoopEngine`: no narration — `narrative` and `suggested_action` are
  both empty strings; the raw deterministic stats are still returned in full,
  same honest degrade as MyScraper/MyResearcher.

## Deterministic pre-work

1. Read the CSV's single numeric value column via stdlib `csv` — no pandas,
   per the harness's dependency-free-runtime rule (see Dependencies below for
   why `numpy` itself is the one exception).
2. Cap at 100,000 samples: if the column has more rows than that, **skip the
   FFT and the Engine call**, `outcome=skipped`, same short-circuit shape as
   MyScraper's fetch-failure skip.
3. Compute the FFT power spectrum via `numpy.fft.rfft`, then the dominant
   frequency (the peak bin's frequency, using `--sample-rate`, default `1.0`
   Hz since v0 does no timestamp-column parsing).
4. Compute mean, standard deviation, and peak amplitude of the raw signal.
5. Only after all of the above succeeds does the Engine call fire.

## Ledger

- **Writes:** `kind=signal_analysis`, `outcome=success|skipped`, `detail`=
  "analyzed `<file>`, dominant freq `<hz>`Hz" or the skip reason,
  `data={file, n_samples, sample_rate, dominant_freq_hz, truncated,
  comment_url}`.
- **Reads:** none — each run is stateless, one file per invocation.

## Guard & Workspace

**No `Workspace`, no PR.** Read-only utility, same posture as MyScraper: no
edits, nothing committed. Output goes to stdout (`--json`) and/or, if
`--issue`/`--repo`/`--comment` are given, an issue comment via
`Action(kind="bash", ...)` routed through `Policy.evaluate()` (default-allow
`Policy`, no `MyGuard` dependency needed — mirrors MyScraper's `_AllowPolicy`
pattern exactly).

Boundaries:

- No network at all in the deterministic pre-work — the CSV is read from a
  local path only; the only I/O side effect in the whole tool is the optional
  issue comment.
- The 100,000-sample cap is a hard skip, not a silent truncation — a signal
  that large either gets analyzed in full or not at all, so the FFT result is
  never computed against a chopped, non-representative window.

## CLI surface

```
mysignalprocessor analyze --file <path> [--sample-rate 1.0] \
                           [--repo owner/name] [--issue N] [--comment] \
                           [--json] [--engine noop|claude-cli] [--engine-model ...] \
                           [--ledger path]
```

## Test plan

- **Happy path:** a synthetic sine-wave CSV fixture at a known frequency, a
  scripted `Engine` reply; assert the FFT correctly identifies the dominant
  frequency within tolerance, `outcome=success`, `kind=signal_analysis` is
  written, `--json` prints the record.
- **Edge (sample cap):** a fixture CSV with more than 100,000 rows; assert
  the FFT and Engine call never happen (spy `Engine`), `outcome=skipped`,
  the reason is recorded.
- **NoopEngine degrade:** assert `narrative`/`suggested_action` are empty
  strings while the raw deterministic stats (`n_samples`, `dominant_freq_hz`,
  `mean`, `std`, `peak`) are still returned in full and the run still
  succeeds.
- Mock nothing for the FFT/statistics path — it runs against real fixture
  data, never mocked; only the `Engine` and the optional `gh` comment call
  are test doubles.

## Dependencies & build order

Depends on core `ledger` and `policy` only — no `github`/`isolation` needed
beyond the same optional-comment touchpoint MyScraper already has. Runtime
dependency on `numpy>=1.26` for the FFT — this is the fleet's second
precedent (after `my-raytracer`) for a tool depending on a **compute
library**, not an API SDK; the harness's dependency-free-runtime rule targets
SDKs/API clients, and a math library used for a purely local, deterministic
computation doesn't reintroduce the coupling that rule guards against.
Standalone; no dependency on any other tool.

**Open questions (resolved for v0, revisit only if requirements change):**

- **Tool-agnostic suggestions.** Resolved: the Engine's `suggested_action`
  never names another My[X] tool by name, so this tool's output doesn't
  assume a particular fleet composition.
- **Input scope.** Resolved: local CSV file path only for v0. Issue
  attachments and URLs are deferred to a later version if requested.
- **Sample rate.** Resolved: a `--sample-rate` flag, default `1.0` Hz — no
  timestamp-column inference in v0.
