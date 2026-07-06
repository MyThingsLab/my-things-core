# MyGroomer — design plan

## Purpose

Turns raw issues into ready, labeled units of work (splitting oversized
issues, applying backlog labels). Package `mygroomer`, backlog label
`my-groomer` (consumes issues *without* a `ready` label; produces issues
*with* one). Owns the **Mother/leaf lifecycle** —
see [ISSUE_HIERARCHY.md](ISSUE_HIERARCHY.md) for the full convention: an
oversized raw issue becomes a long-lived `mother` issue that MyGroomer
revisits across many runs, incrementally spawning small `leaf` issues
(each scoped to one tool's one Engine call) until the mother is closed.

## The single Engine call

Required.

- **Input:** `EngineRequest.prompt` = the raw issue title + body.
  `context = {"issue_number": N, "known_labels": [str, ...]}` (the
  repo's existing label set, fetched deterministically, so the model picks
  from real labels rather than inventing new ones).
- **Output:** `data = {"action": "label" | "split", "labels": [str, ...],
  "subissues": [{"title", "body"}, ...] }`. `"label"` just tags the issue;
  `"split"` proposes leaves (MyGroomer creates them, doesn't guess a count
  itself — that judgment is the whole point of this Engine call, bounded to
  one batch at a time, see pre-work). The same call is reused, unchanged,
  whether it's carving the first batch out of a fresh mother or the next
  batch out of an already-open one.
- Against `NoopEngine`: `data` absent → MyGroomer falls back to
  `action="label"` with a single deterministic default label
  (`needs-triage`), so the issue is still marked as seen rather than left
  untouched.

## Deterministic pre-work

MyGroomer's pre-work now branches into four modes — see
[ISSUE_HIERARCHY.md](ISSUE_HIERARCHY.md) for the full rationale. Only modes
1 and 3 spend the Engine call; modes 2 and 4 are pure housekeeping.

1. List open issues without a `ready`/`in-progress`/`done`/`mother`/`leaf`
   label (the "raw" backlog) via `github.GitHub.list_issues`, plus all
   open `mother`-labeled issues (checked every run regardless of age, since
   an open mother's next batch may already be ready to spawn).
2. Fetch the repo's full label set (`gh label list --json name`) — this
   becomes `known_labels`.
3. **Mode select, per candidate:**
   - **Fresh raw issue, split candidate** (body over N lines, default 100,
     or multiple distinct `## ` headers): relabel `mother`, call the
     Engine for an initial bounded batch (default cap 3–5 leaves), each
     leaf labeled `leaf` + its target tool's backlog label + (once real
     Engine backends exist) `engine:cheap`, with `Part of #<mother>` in
     its body; the mother's body becomes a live checklist of the leaves.
   - **Fresh raw issue, not a split candidate:** unchanged from before —
     Engine call decides `action="label"`.
   - **Open mother, current leaf batch not all closed:** skip
     (`outcome=skipped`), no Engine call — wait for the batch to clear.
   - **Open mother, current batch all closed, more content remains:**
     re-run the same split heuristic against whatever of the mother's
     original body hasn't yet been carved into a leaf; if still
     split-worthy, call the Engine for the next batch, same shape as the
     first.
   - **Open mother, current batch all closed, nothing left to decompose:**
     close it (`gh issue close`) — deterministic, no Engine call.
4. Process one candidate per invocation, oldest-first, but **prefer
   continuing an already-open mother's next batch over starting a new
   one** — mirrors MyOrchestrator's same preference (see
   [my-orchestrator.md](my-orchestrator.md)) and keeps open work from
   sprawling across many started-but-not-progressing epics.

## Ledger

- **Writes:** `kind=groom`, `outcome=success|skipped`, `detail`="labeled
  #N" / "created mother #N with k leaves" / "spawned k more leaves under
  #N" / "closed mother #N", `data={issue, action, labels, subissue_numbers,
  mother}`.
- **Reads:** nothing beyond `list_issues` (live GitHub state — the
  `ready`/`mother`/`leaf` labels and the mother's checklist state — is the
  source of truth; no need to cross-check the ledger to avoid
  double-processing).

## Guard & Workspace

- No `Workspace` — MyGroomer only calls the GitHub issue API (label, create
  leaf, close a mother, comment linking parent↔children), never touches the
  git tree, never opens a PR.
- Every mutating call (`gh issue edit --add-label`, `gh issue create`,
  `gh issue close`) is an `Action(kind="bash", ...)` through `Policy`.
  MyGuard's defaults allow these (no merge/push/destructive-command pattern
  matches); a repo wanting to cap "how many leaves per batch" would add
  that as a MyGuard rule on `Action(kind="issue-split", payload={"count":
  k})`, which means MyGroomer must emit that richer `Action.kind`/
  `payload` (not just `"bash"`) for the split path specifically, so Guard
  has something structured to evaluate. Closing a mother is its own
  `Action(kind="issue-close", payload={"issue": N, "reason": "..."})` for
  the same reason — a repo might want to gate closes distinctly from
  splits.
- Leaves get a body line linking back to the mother (`Part of #N`) and the
  mother's checklist comment is edited (not re-posted) to add the new
  batch — this is deterministic formatting, not model output.

## CLI surface

```
mygroomer next [--repo owner/name]              # groom the single next candidate
mygroomer next --issue <number>                  # groom a specific issue or mother
```

## Test plan

- **Happy path (label only):** a fixture issue under the length threshold;
  scripted Engine reply `{"action": "label", "labels": ["bug", "ready"]}`;
  assert `gh issue edit --add-label` is called with exactly those labels and
  ledger `outcome=success`.
- **Edge case (fresh split → mother created):** a fixture issue with 3
  `## ` headers and 150 lines; scripted Engine reply proposing 3 leaves;
  assert the issue is relabeled `mother`, 3 `gh issue create` calls happen
  (each `leaf`-labeled with `Part of #N`), one checklist comment on the
  mother, and `data.subissue_numbers` has 3 entries.
- **Edge case (mother batch in progress → skip):** an open `mother` issue
  whose linked leaves aren't all closed; assert no Engine call (spy
  `Engine`) and `outcome=skipped`.
- **Edge case (mother batch done, more to spawn):** an open `mother` whose
  current leaves are all closed but body content remains split-worthy;
  assert a new Engine call fires and a new batch of leaves is created,
  linked to the same mother.
- **Edge case (mother fully done → close):** an open `mother` whose
  leaves are all closed and nothing split-worthy remains; assert no
  Engine call, `gh issue close` is called on the mother, and
  `outcome=success` with `detail`="closed mother #N".
- Mock `github.Runner` only.

## Dependencies & build order

Depends on core `ledger`, `policy`, `github` (needs `list_issues` already
present; add `create_issue`, `add_labels`, `list_labels`, `close_issue` —
new thin methods on `github.GitHub`, same pattern as existing ones, not a
new contract). Also depends on the mother/leaf convention in
[ISSUE_HIERARCHY.md](ISSUE_HIERARCHY.md), which this doc now implements.
Build last among the five — it's the one whose Engine call has the widest
judgment surface (splitting is genuinely ambiguous) and benefits from
MySearcher/MyReviewer's patterns being proven first.

**Open questions:**
- Leaf creation via `gh issue create` doesn't natively support parent/child
  linking (that's a GitHub Projects/sub-issues API feature, still
  evolving) — v0 assumes a plain comment-based link (`Part of #N`), not
  the native sub-issues API; revisit once that API stabilizes.
- Extending `github.GitHub` with three new methods is a core-contract
  change like MyReviewer's `diff()` — same flag-before-implementing rule
  applies. Closing an issue (`gh issue close`) needs a fourth new method,
  same rule.
- Batch size (3–5) and "nothing left to decompose" are both left concrete
  to the implementation — see [ISSUE_HIERARCHY.md](ISSUE_HIERARCHY.md)'s
  own open questions, which are really this doc's too.
