---
tool: MyProfessor
repo: my-professor
package: myprofessor
status: designed
added: 2026-07-08
backlog_label: my-professor
engine_call: write a lesson / grade this answer
ledger_kinds: [lesson, grade]
depends_on: [tool:my-knowledger]
---

# MyProfessor — design plan

## Purpose

Given a "teach me" or "quiz me" issue labeled `my-professor` for a topic
that already has a briefed corpus (via MyResearcher/MyKnowledger),
produces a lesson — an explanation plus comprehension questions — or
grades a submitted answer against the cited source material. Package
`myprofessor`, backlog label `my-professor`.

MyProfessor teaches/quizzes on any *one* topic already reachable through
MyKnowledger's external-literature corpus, independent of whether that
topic arrived via MyUni's curriculum or was asked about ad hoc — same
"corpus, not caller" independence MyKnowledger itself already holds from
MyWiki/MySearcher.

## The single Engine call

Two subcommands, each a separate invocation making exactly one Engine call
(same per-run discipline as MyResearcher's `brief`/`plan` split).

### `lesson` (per topic)

Required: "using only these excerpts, write a lesson: an explanation plus
N comprehension questions."

- **Input:** the topic issue title + body, plus the same
  `graphify query "<topic>"` shortlist MyKnowledger's `ask` uses.
  `context = {"topic_issue": N, "question_count": int}`.
- **Output:** `data = {"explanation": str, "questions": [{"q": str,
  "expects": str}], "cited": [source_id, ...]}` — same cite-only
  discipline as MyKnowledger: the explanation may only draw on the given
  excerpts.
- Against `NoopEngine`: prints the retrieved excerpts verbatim, no
  questions — same honest degrade as MyKnowledger's `ask`.

### `grade` (per submitted answer)

Required: "grade this answer against the cited source excerpts and
explain the correct one."

- **Input:** the submitted answer (an issue comment), plus the original
  lesson's `expects` field and `cited` excerpts, recovered from that
  lesson's own ledger entry (not re-derived). `context = {"lesson_issue":
  N, "comment_id": int}`.
- **Output:** `data = {"verdict": "correct"|"partial"|"incorrect",
  "explanation": str}`.
- Against `NoopEngine`: fixed `verdict="partial"`, explanation = the
  cited excerpt verbatim — honest stub, not a fabricated grade.

## Deterministic pre-work

### `lesson`

1. Read the topic issue (label `my-professor`).
2. Run `graphify query "<topic>"` against the external corpus (identical
   retrieval step to MyKnowledger's `ask`), capped the same way.
3. If retrieval returns nothing, skip the Engine call and post "no source
   found to teach `<topic>` from" — same short-circuit as MyKnowledger.

### `grade`

1. Read the target comment and its parent lesson issue.
2. Read that topic's last `kind=lesson` ledger entry to recover `expects`
   and `cited` — grading never re-runs retrieval or re-derives the
   expected answer, it reuses what `lesson` already produced.
3. If no prior `kind=lesson` entry exists for the issue, skip the Engine
   call and post "no lesson found for this issue — run `myprofessor
   lesson` first."

## Ledger

- **`lesson` writes:** `kind=lesson`, `outcome=success|skipped`,
  `detail`="lesson for `<topic>` (`n` questions)", `data={topic_issue,
  question_count, cited, comment_url}`.
- **`grade` writes:** `kind=grade`, `outcome=success|skipped`,
  `detail`="grade for `<topic>` (`verdict`)", `data={lesson_issue,
  comment_id, verdict, comment_url}`.
- **Reads:** `grade` reads the topic's prior `kind=lesson` entry; `lesson`
  reads nothing beyond the external graph (re-teaching a topic is
  allowed, same as MyKnowledger's repeat-question case).

## Guard & Workspace

Comment-only, no `Workspace`, no PR — `ALLOW` by default, same as
MyKnowledger.

## CLI surface

```
myprofessor lesson --issue <number> [--questions 3]
myprofessor grade  --issue <number> --comment <id>
```

## Test plan

- **`lesson` happy path:** fixture corpus + scripted `Engine` reply with
  explanation + questions; assert the comment renders all fields and
  `kind=lesson`/`outcome=success` is written.
- **`lesson` edge (no match):** retrieval returns nothing; assert the
  Engine is never called (spy `Engine`) and `outcome=skipped`.
- **`grade` happy path:** a fixture prior `kind=lesson` entry + a
  submitted answer; scripted `Engine` verdict; assert the comment renders
  the verdict + explanation and `kind=grade`/`outcome=success` is written.
- **`grade` edge (no prior lesson):** assert the Engine is never called
  and `outcome=skipped`.
- Mock `github.Runner` and the `graphify` CLI boundary; the ledger-based
  hand-off between `lesson` and `grade` runs against real fixture ledger
  entries, never mocked.

## Dependencies & build order

Depends on MyKnowledger's retrieval pattern and its pre-bootstrapped
external corpus (inherits the same "never ingests" invariant). Build
after MyKnowledger. Independent of MyUni — MyUni decides *what* to teach
a curriculum of; MyProfessor teaches/quizzes on any one topic already in
the corpus, regardless of how it got there.

**Open questions:**

- Whether `grade` should ever gate anything mechanically (e.g. mark a
  topic "mastered" and skip re-teaching it) — left as a future
  refinement, not v0, same stance MyAdvisor's doc takes on its own
  `confidence` field.
- Where quiz/answer history lives long-term — ledger-only for v0 vs. a
  dedicated per-topic progress file; not decided.
- Whether `lesson`'s question count should scale with excerpt count
  rather than always defaulting to a fixed N — not decided, `--questions`
  stays a manual override for v0.
