# MyGroomer — design plan

## Purpose

Turns raw issues into ready, labeled units of work (splitting oversized
issues, applying backlog labels). Package `mygroomer`, backlog label
`my-groomer` (consumes issues *without* a `ready` label; produces issues
*with* one).

## The single Engine call

Required.

- **Input:** `EngineRequest.prompt` = the raw issue title + body.
  `context = {"issue_number": N, "known_labels": [str, ...]}` (the
  repo's existing label set, fetched deterministically, so the model picks
  from real labels rather than inventing new ones).
- **Output:** `data = {"action": "label" | "split", "labels": [str, ...],
  "subissues": [{"title", "body"}, ...] }`. `"label"` just tags the issue;
  `"split"` proposes sub-issues (MyGroomer creates them, doesn't guess a
  count itself — that judgment is the whole point of this Engine call).
- Against `NoopEngine`: `data` absent → MyGroomer falls back to
  `action="label"` with a single deterministic default label
  (`needs-triage`), so the issue is still marked as seen rather than left
  untouched.

## Deterministic pre-work

1. List open issues without a `ready`/`in-progress`/`done` label (the
   "raw" backlog) via `github.GitHub.list_issues`.
2. Fetch the repo's full label set (`gh label list --json name`) — this
   becomes `known_labels`, keeping the Engine call closed-vocabulary.
3. Cheap heuristic pre-filter: an issue body over N lines (default 100) or
   containing multiple distinct `## ` headers is a **split candidate**;
   flag this in `context` as `{"likely_split": true}` so the model isn't
   guessing that too — it only decides labels/sub-issue boundaries.
4. Process issues oldest-first, one per invocation (mirrors the harness's
   "one unit of work" rule — MyGroomer grooms one issue per run, not the
   whole backlog, so a CI schedule naturally rate-limits it).

## Ledger

- **Writes:** `kind=groom`, `outcome=success`, `detail`="labeled #N" or
  "split #N into k sub-issues", `data={issue, action, labels, subissue_numbers}`.
- **Reads:** nothing beyond `list_issues` (live GitHub state is the source
  of truth for "already groomed" via the `ready` label itself — no need to
  cross-check the ledger to avoid double-processing).

## Guard & Workspace

- No `Workspace` — MyGroomer only calls the GitHub issue API (label, create
  sub-issue, comment linking parent↔children), never touches the git tree,
  never opens a PR.
- Every mutating call (`gh issue edit --add-label`, `gh issue create`) is an
  `Action(kind="bash", ...)` through `Policy`. MyGuard's defaults allow
  these (no merge/push/destructive-command pattern matches); a repo wanting
  to cap "how many sub-issues per split" would add that as a MyGuard rule
  on `Action(kind="issue-split", payload={"count": k})`, which means
  MyGroomer must emit that richer `Action.kind`/`payload` (not just
  `"bash"`) for the split path specifically, so Guard has something
  structured to evaluate.
- Split sub-issues get a body line linking back to the parent (`Part of
  #N`) and the parent gets a checklist comment listing them — this is
  deterministic formatting, not model output.

## CLI surface

```
mygroomer next [--repo owner/name]              # groom the single oldest raw issue
mygroomer next --issue <number>                  # groom a specific issue
```

## Test plan

- **Happy path (label only):** a fixture issue under the length threshold;
  scripted Engine reply `{"action": "label", "labels": ["bug", "ready"]}`;
  assert `gh issue edit --add-label` is called with exactly those labels and
  ledger `outcome=success`.
- **Edge case (split):** a fixture issue with 3 `## ` headers and 150 lines;
  scripted Engine reply proposing 3 sub-issues; assert 3 `gh issue create`
  calls, one linking comment on the parent, and `data.subissue_numbers` has
  3 entries.
- Mock `github.Runner` only.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs `list_issues` already
present; add `create_issue`, `add_labels`, `list_labels` — new thin methods
on `github.GitHub`, same pattern as existing ones, not a new contract).
Build last among the five — it's the one whose Engine call has the widest
judgment surface (splitting is genuinely ambiguous) and benefits from
MySearcher/MyReviewer's patterns being proven first.

**Open questions:**
- Sub-issue creation via `gh issue create` doesn't natively support
  parent/child linking (that's a GitHub Projects/sub-issues API feature,
  still evolving) — v0 assumes a plain comment-based link (`Part of #N`),
  not the native sub-issues API; revisit once that API stabilizes.
- Extending `github.GitHub` with three new methods is a core-contract
  change like MyReviewer's `diff()` — same flag-before-implementing rule
  applies.
