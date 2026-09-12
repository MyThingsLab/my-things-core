# ADR 0005 — the CAD label schema + priority-queue sort key

- **Status:** Accepted (2026-09-12)
- **Issue:** [my-things-core#147](https://github.com/MyThingsLab/my-things-core/issues/147)
- **Related:** part of `goal/cad-foundation`

## Context

The 22-label CAD schema (`lane:*`, `prio:*`, `kind:*`, `size:*`, `state:*`) is
already live on the 9 kernel repos, but only as labels attached through the
GitHub UI/CLI by hand. Nothing records the vocabulary as data. Every consumer
that needs it — `my-orchestrator` ranking the backlog, `my-architect` filing
issues, `my-coder` picking up work, the acceptance gate deciding what's
dispatchable — would otherwise each re-hardcode the label names, colors, and
allowed values, and drift the moment one of them adds a typo or a new value.
The same applies to the priority queue: without one shared `sort_key`, each
consumer invents its own scoring, and "why did this issue dispatch before
that one" stops being answerable in one line of a PR body.

## Decision

**Promote into core**, as `mythings.labels`. Same class of thing as
`mythings.corpus` (ADR 0001), `mythings.mastery` (ADR 0002),
`mythings.embed` (ADR 0003), and `mythings.plan` (ADR 0004): a seam, not a
sixth load-bearing contract. `harness.md` names five (`ledger`, `policy`,
`engine`, `github`, `isolation`) and says not to add a sixth lightly.

## The API

```python
LabelDef(name, color, description)
SCHEMA: tuple[LabelDef, ...]              # the 22 labels, one canonical table

Facets(lane=None, prio=None, kind=None, size=None, state=None, unknown=())
parse(labels)                              -> Facets
Validation(dispatchable, reasons=())
validate(facets)                           -> Validation

QueueItem(repo, number, labels=(), age_days=0.0)
sort_key(issue)                            -> tuple

sync(repo, *, runner=_gh)                  -> None
```

- **`SCHEMA`** is the one canonical table — name, color, description for
  each of the 22 labels (4 `lane`, 4 `prio`, 7 `kind`, 3 `size`, 4 `state`).
  `parse()`'s allowed-value sets and `sync()`'s label set both derive from
  this one list, so the vocabulary can only drift by editing it.
- **`parse(labels)`** pulls `lane`/`prio`/`kind`/`size`/`state` off a raw
  label list. Anything that isn't a recognized `"<facet>:<value>"` pair —
  a backlog label like `my-idea`, a tool's own backlog label, a typo, an
  unrecognized value for a known facet prefix — passes through untouched in
  `Facets.unknown` rather than being dropped or raising. Tolerating unknown
  labels is the point: this schema shares label-list space with each repo's
  own backlog label and any ad hoc labels a human adds.
- **`validate(facets)`** says explicitly why an issue isn't dispatchable
  rather than defaulting a missing field to some assumed value: no `lane`,
  no `size`, `size:L` (too large to dispatch as one unit), and
  `state:blocked` are each named as an explicit reason.
- **`sort_key(issue)`** is `(not critical, lane_rank, prio_rank, -age_days,
  repo, number)` — lexicographic, no tuning constants, explainable in one
  line of a PR body. `critical` is the plain `critical` label (the
  fleet-wide severity label from `docs/CONVENTIONS.md`'s "Filing bugs"
  section, unrelated to the CAD facets) and always wins outright. `lane` and
  `prio` rank in the order given in the schema (`core` before `kernel`
  before `product` before `external`; `P0` before `P1` before `P2` before
  `P3`); an issue with no lane/prio ranks after every recognized value
  rather than being silently treated as the best case — the same
  fail-closed choice `plan.ready()` makes for a dangling dependency. Age
  breaks ties oldest-first, and `(repo, number)` is the deterministic tail
  that guarantees no two distinct issues ever tie.
- **`sync(repo, *, runner=_gh)`** calls `gh label create --force` once per
  schema entry. `--force` creates the label if absent and overwrites
  color/description if it already exists, so `sync()` is idempotent against
  a repo that already has the schema without a separate list-then-diff step.

No `Engine` call anywhere in this module — everything here is data plus pure
functions, same as `plan.ready()`/`plan.reconcile()`'s deterministic half.

Preserves the same three properties every core module must (ADR 0001, 0002,
0003, 0004):

1. **Zero new dependencies.** Pure stdlib (`dataclasses`, `collections.abc`);
   `sync()` reuses `github.Runner`/`github._gh`, the same shell-out `plan.py`
   already depends on.
2. **No import-time side effects.** Nothing touches disk or the network
   until a caller calls `sync()`.
3. **Inert by default.** No tool reads or writes labels unless it opts in.

## Consequences

- `my-orchestrator` can rank the backlog by `sort_key` instead of inventing
  its own scoring.
- `my-architect`/`my-groomer` can validate an issue's dispatchability before
  filing or promoting it, and `sync()` gives every kernel/product repo an
  idempotent way to (re-)apply the schema.
- Nothing existing changes. `mythings.labels` is inert until a consumer
  opts in.
