# ADR 0002 — the shared "record-and-rank-mastery" seam

- **Status:** proposed
- **Date:** 2026-07-10
- **Related:** [ADR 0001](0001-corpus-seam.md) (the corpus seam this completes)

## Context

`mythings.corpus` (ADR 0001) gave the study cluster its **read** side: pull the
relevant excerpts from a curriculum and cite them. It left the loop open. Today
the study pipeline is write-only — `my-uni` files topic issues, `my-researcher`
writes cited briefs, `my-glossary` defines terms — and **nothing records what the
learner has and has not mastered, or decides what to study next.**

That feedback state is to the learn-loop exactly what GitHub issues + the
dev-ledger are to the build-loop (`fleet_cycle.py`): the durable signal that
drives the next unit of work. Four planned consumers — `my-professor`,
`my-syllabus`, `my-flashcards`, `my-grader` — all need it, and would each invent
their own record format if it is not settled first. That is the same
five-tools-before-the-seam mistake ADR 0001 avoided, so the seam comes first.

## Decision

**Promote into core**, as `mythings.mastery`: an append-only ledger of graded
attempts plus the pure functions that roll them up into a per-topic mastery
picture and a spaced-repetition schedule.

**The ledger is local JSONL, not a PR per answer.** A cram session grades one
answer every few seconds; routing each through the issue→PR→CI ceremony would be
absurd and would defeat the interactive loop. This mirrors the dev-ledger's
append-only local discipline. Only *durable curriculum content* (a syllabus
decomposition, a research brief) lands via PR — the hybrid boundary the user set
for the study cluster. `Action`/`Policy` still governs anything that mutates a
shared repo; the mastery ledger simply is not that.

## The API

```python
record(path, attempt)                             # append one Attempt (JSONL)
load(path)                          -> [Attempt]
rollup(attempts, *, half_life_days=7, now=None) -> [Mastery]   # recency-decayed score/topic
schedule(mastery, *, base_days=1)   -> str | None # next_due ISO, spaced by score & streak
due(masteries, *, now=None, limit=None) -> [Mastery]           # weakest/overdue first
```

- `Attempt(topic, at, score, kind, gaps, source)` — one graded interaction.
  `score` is 0.0–1.0; `gaps` are short phrases of what was missed; `kind` is
  `quiz | flashcard | recall | exam`.
- `Mastery(topic, attempts, score, last_seen, next_due, gaps)` — the derived
  rollup a consumer or the study driver ranks on.

It preserves the same three properties that make a core module every repo
depends on tolerable (ADR 0001):

1. **Zero new dependencies.** Pure stdlib (`json`, `datetime`); core stays
   `dependencies = []`.
2. **No import-time side effects.** Nothing touches disk until a caller passes a
   path, mirroring `Ledger(path)` and `mythings.corpus`.
3. **Inert by default.** No tool records or reads mastery unless it opts in.

### Recency decay, not a plain mean

`rollup` weights each attempt by `0.5 ** (age_days / half_life_days)`, so a fresh
success outweighs a stale failure. Cramming is non-stationary — what matters is
what you know *now*, not your all-time average — and a plain mean would keep
punishing a topic long after you learned it.

### Spacing squares the score

`schedule` sets the interval to `base_days * (1 + attempts) * score²`. Squaring
keeps a half-known topic (score ~0.5) resurfacing soon while a genuinely mastered
one (score ~1.0) earns real spacing. A score-0 topic is due immediately. This is
a deliberately simple SM-2-flavoured rule, not the full algorithm; the contract
is `due()`'s ordering, which a consumer can refine later without changing callers.

## Consequences

- `my-professor` is built next as the **thinnest consumer** that both writes
  (`grade` → `record`) and reads (`quiz` ordered by `due`), exercising the
  contract on the real UL corpus before the other three depend on it.
- `re-rank` in the study loop reads `due()` directly (local); `my-planner` stays
  for the durable "what topic to research next" decision. The cram loop is not
  routed through issues or PRs.
- Nothing in the build-loop changes. `mythings.mastery` is inert until a study
  tool opts in.
