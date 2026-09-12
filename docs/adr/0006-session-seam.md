# ADR 0006 — the session/goal record store

- **Status:** Accepted (2026-09-12)
- **Issue:** [my-things-core#148](https://github.com/MyThingsLab/my-things-core/issues/148)
- **Related:** part of `goal/cad-foundation`

## Context

The CAD loop has no durable representation of *a unit of work and its verdict*.
`mythings.ledger` records events as they happen — good for audit, useless for
asking "what is task 7 and did it land". `.fleet-dispatch/ledger.jsonl` holds
ad-hoc `Attempt` rows invented inside `fleet_dispatch.py`, readable only by the
script that wrote them. Between the two, nothing survives a session boundary in
a queryable shape, which is exactly why a goal spanning 30 sessions cannot
today be resumed, measured, or audited: each session starts by re-deriving
state from git and GitHub, and re-derives it slightly differently.

The specific losses are worth naming, because they are the ones this ADR is
paying for. A worker killed mid-task leaves a branch and no record that it was
ever running. A task rejected by the acceptance gate leaves a comment on a PR
and nothing a scheduler can read. And a worker that spent an hour proving an
approach does not work leaves nothing at all — the next worker tries it again.

## Decision

**Promote into core**, as `mythings.session`. Same class of thing as
`mythings.corpus` (ADR 0001), `mythings.mastery` (ADR 0002), `mythings.embed`
(ADR 0003), `mythings.plan` (ADR 0004), and `mythings.labels` (ADR 0005): a
seam, not a sixth load-bearing contract. `harness.md` names five (`ledger`,
`policy`, `engine`, `github`, `isolation`) and says not to add a sixth lightly.

Append-only JSONL, the same discipline as `mythings.mastery`: a write is one
line, history is never rewritten, and a task's current state is the last line
mentioning it. Not a database, and deliberately not a PR per state change —
a worker updating a task's state must not cost a review cycle.

## The API

```python
TaskState                                  # ready|running|blocked|done|rejected|needs_human
Outcome                                    # accepted|rejected|needs_human
Check(name, passed, detail="")             # passed: True | False | None
Verdict(outcome, checks=(), reason="")

TaskRecord(session_id, task_id, lane="", repo="", issue=None, depends_on=(),
           state=READY, attempts=0, budget_usd=0.0, spent_usd=0.0,
           branch="", pr=None, verdict=None, notes_for_peers="")
GoalRecord(goal_id, project="", lane="", statement="", done_when=(), phases=(),
           milestone=None, opened="", expires="", session_budget=0,
           usd_budget=0.0, sessions_used=0, state="open")
GoalJournalEntry(session_id, ts, goal_id="", accepted=(), rejected=(),
                 dead_ends=(), decisions=(), spent_usd=0.0)

record(path, rec)      -> None             # append one line
load(path)             -> list[Record]     # every record, in file order
tasks(records)         -> list[TaskRecord] # last line per task_id
goals(records)         -> list[GoalRecord] # last line per goal_id
journal(records)       -> list[GoalJournalEntry]   # every entry, never collapsed
ready(tasks)           -> list[TaskRecord]
running(tasks)         -> list[TaskRecord]
now_iso(now=None)      -> str
```

- **One store, three record kinds**, tagged by a `record` field on each line.
  A goal, its tasks, and its journal share a file because they are read
  together — a resuming session wants all three or none.
- **`tasks()`/`goals()` collapse, `journal()` does not.** Task and goal rows are
  state, so the last line wins; journal entries are events, so every one is
  kept. Dict insertion order keeps the collapsed lists in first-seen order.
- **`ready()`** mirrors `plan.ready()`, including its fail-closed treatment of a
  dangling dependency: a `depends_on` id with no matching task counts as unmet,
  never as done. It also skips `running` and the three terminal states, so what
  it returns is dispatchable, not merely unblocked.
- **`running()`** is the resume path. Rows still marked `running` when a store
  is reopened were interrupted — nothing writes that state on a clean exit —
  and are the first thing a recovering session reconciles.
- **`Verdict`/`Check`** are the persisted form of the acceptance gate's
  assessment (`myfleet.accept`), three-way `passed` included. `None` for "could
  not be evaluated" is load-bearing and survives the round trip: collapsing it
  into `False` turns "I cannot tell" into "it is bad", and a gate that cannot
  record "I don't know" eventually records "yes".
- **`notes_for_peers` and `dead_ends`** are the only inter-worker and
  inter-session channel. Everything else about a task is recoverable from
  GitHub; *we tried X, it does not work, because Y* is recoverable from
  nowhere. Bounded strings, never conversations — `notes_for_peers` is capped
  at `NOTES_MAX` (500) chars, truncated rather than rejected because the writer
  is a model at the end of a session and losing the whole record to a
  `ValueError` costs more than losing the tail of a sentence.

### A torn last line is not corruption

`load()` drops an unparseable **final** line and raises `CorruptStore` for one
anywhere else. This is the one place the module is lenient, and the asymmetry
is the point: a half-written last line is the expected failure mode of an
append-only file whose writer was killed — which, for a store whose entire
purpose is surviving killed workers, is not an error condition. A bad line in
the middle means the file was rewritten or two writers interleaved, which is a
real fault and gets raised rather than silently skipped.

No `Engine` call anywhere in this module — pure data and IO.

Preserves the same three properties every core module must (ADR 0001–0005):

1. **Zero new dependencies.** Pure stdlib (`json`, `dataclasses`, `enum`,
   `datetime`, `pathlib`).
2. **No import-time side effects.** Nothing touches disk until `record()` or
   `load()` is called.
3. **Inert by default.** No tool reads or writes a session store unless it
   opts in.

## Consequences

- `my-fleet` can persist `Attempt`s as `TaskRecord`s in a shape other tools
  read, and persist `myfleet.accept`'s `Assessment` as a `Verdict` instead of
  printing it and forgetting it.
- `my-orchestrator`/`my-director` gain a resumable backlog: `ready()` for what
  to dispatch, `running()` for what to recover, the journal for what a previous
  session already ruled out.
- `mythings.session` is not exported from `mythings/__init__.py`. The public
  API is contracts only, and `Session` there already means
  `mythings.testers.Session` — a chat session with a human tester, an unrelated
  thing. Consumers import `mythings.session` by module.
- Nothing existing changes. The module is inert until a consumer opts in.
