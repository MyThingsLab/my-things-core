---
tool: MyUni
repo: my-uni
package: myuni
status: shipped
added: 2026-07-08
backlog_label: my-uni
engine_call: decompose this field into an ordered curriculum
ledger_kinds: [curriculum]
depends_on: []
---

# MyUni — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-uni's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-uni/README.md`](../../../my-uni/README.md) and
> [`my-uni/CLAUDE.md`](../../../my-uni/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


## Purpose

Given a "field of study" issue labeled `my-uni` (e.g. "Computer Science,
undergrad-equivalent depth"), decomposes the field into a curriculum: an
ordered set of topics with prerequisites, each opened as its own issue
labeled both `my-uni` and `my-researcher` so **MyResearcher** picks it up
on its own schedule and produces a cited study brief for it. Package
`myuni`, backlog label `my-uni`.

MyUni is deliberately **upstream** of MyResearcher, not a duplicate of it:

- **MyResearcher's `plan` mode** orders topics it's *given* into a study
  path — it doesn't decide what the topics of a field are.
- **MyUni** decides what the topics of a field *are* in the first place,
  then hands each one to MyResearcher via a plain GitHub issue — loose
  coupling through the issue tracker, not a code dependency between the
  two tools.

MyUni never builds or ingests a knowledge corpus itself — see Open
questions on how this interacts with MyKnowledger's "never ingests"
invariant, which it inherits by construction (it only *opens issues*,
same as MyGroomer's issue-creation side effect).

## The single Engine call

Required: "decompose this field into a curriculum: an ordered list of
topics, each with a one-line rationale and its prerequisites."

- **Input:** the field issue title + body, plus (on a re-run) the titles
  of topic issues already opened under the same field so the run extends
  a curriculum rather than re-proposing what already exists. `context =
  {"field_issue": N, "existing_topics": [str, ...]}`.
- **Output:** `data = {"topics": [{"title": str, "rationale": str,
  "prereqs": [title, ...]}]}` — topics may only reference `prereqs` from
  within the same list (no forward reference to an undeclared topic).
- Against `NoopEngine`: emits the field issue's own title as the sole
  topic, no decomposition — honest stub.

## Deterministic pre-work

1. Read the field issue (label `my-uni`).
2. Gather already-opened topic issues under the same field (matched by a
   `part-of: #N` marker in the topic issue body, written at creation
   time) for the `existing_topics` context and for dedupe.
3. **Post-Engine, deterministic dedupe:** drop any proposed topic whose
   title case-insensitively matches an existing one — MyUni extends a
   curriculum, it never re-proposes a topic MyResearcher may already be
   briefing.
4. Cap the curriculum to a fixed size per run (default 12) — deterministic
   truncation, doesn't trust the model's enthusiasm for how big a "field"
   is.

## Deterministic post-work

For each surviving proposed topic, `create_issue` (the new
`github.GitHub` method already flagged in
[BUILD_GUIDE.md](BUILD_GUIDE.md)'s consolidated batch, shared with
MyGroomer) labeled `my-uni` **and** `my-researcher`, body carrying the
rationale, prereqs, and a `part-of: #N` marker back to the field issue.
MyUni never calls MyResearcher's CLI directly — it only opens issues
MyResearcher already watches for.

## Ledger

- **Writes:** `kind=curriculum`, `outcome=success`, `detail`="curriculum
  for `<field>` (`n` new, `m` already open)", `data={field_issue,
  topics_opened: [issue_number, ...], topics_deduped: [title, ...]}`.
- **Reads:** existing topic issues under the field, for dedupe context.

## Guard & Workspace

No `Workspace`, no PR — the side effect is a series of `create_issue`
calls, each an `Action` (new kind, e.g. `"issue-create"`, same granularity
question MyGroomer's doc already flags) through `Policy.evaluate()`,
`ALLOW` by default — opening issues is low-risk and reversible (a human
can close any of them).

## CLI surface

```
myuni plan --issue <number> [--max-topics 12]
```

## Test plan

- **Happy path:** a fixture field issue with no existing topics; scripted
  `Engine` curriculum of 5 topics; fake `github.Runner`; assert 5 new
  issues open with both labels, each carrying the `part-of:` marker, and
  `kind=curriculum`/`topics_opened` has 5 entries.
- **Edge case (all topics already exist):** fixture field issue with 5
  existing topic issues matching the scripted Engine reply's titles;
  assert **zero** new issues open, `outcome=success` (the run did its
  job — it just found nothing new), and `topics_deduped` lists all 5.
- **Edge case (cap exceeded):** scripted Engine reply proposes more than
  `--max-topics`; assert deterministic truncation, not a model-driven cap.
- Mock `github.Runner`; dedupe/truncation logic runs against real fixture
  issue lists.

## Dependencies & build order

Needs the new `github.GitHub.create_issue`/`add_labels` methods already
flagged in [BUILD_GUIDE.md](BUILD_GUIDE.md)'s consolidated batch (shared
with MyGroomer) — build after that batch lands. Soft-depends on
MyResearcher existing to actually consume the opened issues (degrades
gracefully if built first: the issues just sit unpicked-up until
MyResearcher exists). Independent of MyKnowledger and MyProfessor.

**Open questions:**

- **Confirm the MyResearcher seam holds.** MyUni chooses topics,
  MyResearcher orders/briefs them — two ends of one pipeline, not a
  duplicate — but worth re-confirming once both exist rather than merging
  them prematurely, same caution MyResearcher's own doc already flags
  about its `plan` mode vs. my-planner.
- **Curriculum depth as a tunable** (survey vs. undergrad vs. graduate
  depth) — left as issue-body free text for v0, not a structured field.
- **Where the resulting corpus lives**, once MyResearcher briefs feed
  MyKnowledger's external-literature graph — same open question already
  flagged, unresolved, in [my-knowledger.md](my-knowledger.md); MyUni
  doesn't change that answer, it just increases how much ends up needing
  one.
