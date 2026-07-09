---
tool: MyIdea
repo: my-idea
package: myidea
status: shipped
added: 2026-07-08
backlog_label: my-idea
engine_call: required: explore this idea against this fleet
ledger_kinds: [idea_explored, idea_filed]
depends_on: []
---

# MyIdea — design plan

> **Historical.** This is the pre-build design plan, frozen as of my-idea's
> first ship. It is **not** kept in sync with the implementation — for current
> behavior (CLI surface, flags, invariants) read
> [`my-idea/README.md`](../../../my-idea/README.md) and
> [`my-idea/CLAUDE.md`](../../../my-idea/CLAUDE.md) in the tool's own
> repo. Only genuinely cross-tool contracts (a new Engine-seam pattern, a new
> core dependency) get a follow-up edit here.


## Purpose

Turns a rough idea into an **explored** idea. The user files a one-liner
or loose paragraph as a GitHub issue labeled `my-idea` (or creates it via
`myidea new "..."`); `myidea explore` grounds it against what the fleet
already has and posts a structured exploration brief back on the issue:
restatement, overlap with existing tools, contract fit, risks, the
smallest buildable slice, a verdict (build / park / fold into an existing
tool), and probing questions to explore next. Package `myidea`, backlog
label `my-idea`.

This is the front door the 2026-07-08 idea-batch triage did by hand
(15 ideas → drafted / folded / parked): the same judgment, one idea at a
time, on demand, recorded on the issue instead of in a session.

## The single Engine call

Required, in `explore`: "explore this idea against this fleet."

- **Input:** the idea issue title + body, plus deterministically gathered
  grounding — the org's repo names, the `docs/tools/` design index
  titles, and sibling `my-idea` issue titles (for "already being
  explored" overlap). `context = {"idea_issue": N, "org_tools": [...],
  "designed_tools": [...], "sibling_ideas": [...]}`.
- **Output:** JSON `{"restatement": str, "overlaps": [{"tool": str,
  "why": str}], "contract_fit": str, "risks": [str], "smallest_slice":
  str, "verdict": "build|park|fold", "fold_into": str|null, "questions":
  [str]}`. Overlap entries may only name tools present in the given
  grounding lists — same cite-only-what-you-were-given discipline as
  MyResearcher/MyNews.
- Against `NoopEngine`: **no fabricated exploration** — the brief renders
  only the deterministic grounding (keyword-matched candidate overlaps,
  sibling ideas) with an explicit "no judgment engine attached" note.

## Deterministic pre-work

1. Read the idea issue (label `my-idea`).
2. Gather grounding: `gh repo list <org>` names; `docs/tools/*.md`
   design-plan titles via the GitHub contents API (no local core checkout
   assumed); other open `my-idea` issues.
3. Keyword-match the idea text against those lists to seed candidate
   overlaps (also the entire NoopEngine output).

## Ledger

- **Writes:** `kind=idea_explored`, `outcome=success`,
  `detail`="explored #N: <verdict>", `data={idea_issue, verdict,
  fold_into, comment_url}`; `myidea new` writes `kind=idea_filed`.
- **Reads:** none beyond its own history.

## Guard & Workspace

Comment-only by default — the brief posts as an issue comment through
`Policy` (`ALLOW` default, same shape as MyReporter/MyUni side effects).
`--local-only` prints the brief and touches nothing (the Verify seam).
An optional later `--commit` mode could archive `ideas/<slug>.md` via
`Workspace` + PR (MyNews' pattern); **not in v0**.

## CLI surface

```
myidea new "<one-liner>" [--repo owner/name]     # file an idea issue
myidea list [--repo owner/name]                  # open ideas + verdicts
myidea explore --issue N [--repo owner/name]
               [--engine noop|claude-cli] [--local-only]
```

Default `--repo` is the my-idea repo itself: ideas live where the tool
lives unless pointed elsewhere.

## Test plan

- Happy path: scripted `Engine` returning a full brief; fake `gh` runner;
  assert the rendered comment carries verdict/overlaps/questions, the
  comment posts through a spy `Policy`, and `kind=idea_explored` is
  written.
- Edge (NoopEngine): assert no fabricated fields — only keyword-matched
  grounding renders, with the no-engine note.
- Edge (Policy DENY / unattended ASK): brief is printed, comment is not
  posted, outcome recorded honestly.
- `new`/`list` against the fake runner.

## Dependencies & build order

Core `ledger`, `policy`, `engine`, `github`; my-guard. Independent of
everything else; natural sibling of MyPlanner (an explored idea's
"smallest slice" is what MyPlanner would sequence next). Buildable now.

**Open questions:**

- Should `explore` auto-file the "smallest slice" as a labeled backlog
  issue when the verdict is `build`? Recommend no in v0 — keep filing a
  human act; the brief already contains the copy-pasteable slice.
- Whether `my-ideas.md` at the workspace root should be importable
  (`myidea import`) — recommend a later issue once the issue-based flow
  proves itself.
