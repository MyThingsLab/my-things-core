# My[X] tool designs — index

Design docs for the next tools in the MyThingsLab line, all buildable now
against `NoopEngine` (zero tokens), per the harness in
[`../../src/mythings/harness.md`](../../src/mythings/harness.md) and the
seams explained in [`../CONVENTIONS.md`](../CONVENTIONS.md). Each doc below
is self-contained; this page only orders and connects them.

## The tools

| Tool | One line | Engine call | Doc |
|---|---|---|---|
| MyTester | writes a test for one uncovered unit | "write a test for this one uncovered unit" | [my-tester.md](my-tester.md) |
| MyReporter | digests Ledger + dev-ledger into a report | none (optional prose summary) | [my-reporter.md](my-reporter.md) |
| MySearcher | ranks files relevant to an issue | "rank relevant files for this task" | [my-searcher.md](my-searcher.md) |
| MyReviewer | flags correctness bugs on an open PR | "does this diff have a correctness bug?" | [my-reviewer.md](my-reviewer.md) |
| MyGroomer | labels/splits raw issues into ready units | "split/label this issue" | [my-groomer.md](my-groomer.md) |
| MyTelegramBot | pushes ledger notifications; relays `Policy` `ASK` to a human over Telegram | none | [my-telegram-bot.md](my-telegram-bot.md) |
| MyScaffolder | bootstraps a new My[X] tool repo from a proposal | "expand a proposal into the four CLAUDE.md seams" | [my-scaffolder.md](my-scaffolder.md) |
| MyKnowledger | answers "what happened / why" from ledger history | "answer this question using only these ledger excerpts" | [my-knowledger.md](my-knowledger.md) |
| MyAdvisor | recommends a course of action with trade-offs | "recommend an answer, with trade-offs" | [my-advisor.md](my-advisor.md) |
| MyChangelogger | turns ship/fix ledger entries into a CHANGELOG.md section | none | [my-changelogger.md](my-changelogger.md) |
| MyDriftWatcher | flags cross-repo convention drift | none | [my-drift-watcher.md](my-drift-watcher.md) |
| MyGrapher | keeps a repo's knowledge graph fresh for other tools to query | none | [my-grapher.md](my-grapher.md) |
| MyCoder | issue → diff → PR (the "act" tool) | deferred | see stub below |

## Recommended build order

1. **MyTester** — smallest full loop (issue → deterministic pre-work → one
   Engine call → PR → ledger); validates the harness pattern end-to-end
   before anything else copies it. Also the only tool other than MyCoder
   that opens a code-changing PR, so it's the first real test of the
   Guard+Workspace path under load.
2. **MyReporter** — no dependency on the others, but more useful once
   MyTester has produced real ledger history to report on. Can build in
   parallel with MySearcher if capacity allows.
3. **MySearcher** — independent of MyTester/MyReporter. Its ranking logic is
   a dependency for MyReviewer's diff-truncation step and for MyGroomer's
   split-boundary judgment (both reuse "which files matter here"), so
   building it third means those two don't reimplement it.
4. **MyReviewer** — depends on MySearcher's scoring (optional reuse, not a
   hard blocker — falls back to raw changed-line-count) and on a new
   `github.GitHub.diff()` method.
5. **MyGroomer** — last: its Engine call ("split or just label") has the
   widest judgment surface of the five, so it benefits most from the other
   four having already proven the pattern. Depends on three new
   `github.GitHub` methods (`create_issue`, `add_labels`, `list_labels`).
6. **MyTelegramBot** — independent of the other five (no `github`/`engine`/
   `isolation` dependency at all — it only touches `policy` and `ledger`).
   Can be built any time, but is most useful once MyTester can actually
   trigger a real `ASK`, so build it after MyTester if sequencing by payoff
   rather than by dependency.
7. **MyChangelogger** — low complexity, same PR shape as MyTester but
   editing one well-understood file. Build early relative to the rest of
   this second batch, right after MyReporter (shares its ledger-reading
   conventions).
8. **MyKnowledger** — reuses MyReporter's ledger-merging logic; build after
   it. Independent of MySearcher/MyGrapher for v0 (keyword match is enough).
9. **MyGrapher** — build after MySearcher: its purpose is retrofitting
   MySearcher's (and later MyReviewer's) naive shortlist step with a real
   graph query, so MySearcher needs to exist first to have something worth
   retrofitting.
10. **MyScaffolder** — meta relative to every other tool; doesn't pay off
    until several more tool proposals are queued. Build once that backlog
    exists, not first.
11. **MyDriftWatcher** — low urgency while only 2-3 repos exist; drift only
    matters once there's enough repos to diverge. Most valuable once
    MyScaffolder is producing new repos regularly.
12. **MyAdvisor** — last: depends on both MyKnowledger's and MySearcher's
    shortlist logic, and its judgment quality can't be meaningfully
    validated against `NoopEngine` (same limitation as MyCoder).

## Cross-cutting notes

- **Core contract changes are not free.** MyReviewer needs `diff()` and
  MyGroomer needs `create_issue`/`add_labels`/`list_labels` added to
  `github.GitHub`. Per the workspace CLAUDE.md's architectural-change rule,
  each addition should be proposed and confirmed before implementation —
  they're small, thin wrappers in the existing style, not new contracts,
  but they still touch shared code every tool depends on.
- **Guard granularity.** Most tools' side effects are generic
  `Action(kind="bash", ...)`, which MyGuard's default rules already cover
  (merge/force-push/protected-branch/destructive-command patterns).
  MyGroomer's split path is the one place a repo might want a
  *structured* `Action.kind` (e.g. `"issue-split"` with a `payload={"count":
  k}`) so Guard can reason about something more specific than a shell
  string — noted in its doc as an open question, not decided here.
- **First third-party service dependency.** Every tool above only ever
  talks to GitHub. MyTelegramBot is the first to call a service outside
  that boundary (the Telegram Bot API) and the first to need CI secrets
  beyond the `gh`/`git` identity the harness already assumes — both are
  flagged in its doc as decisions to confirm before implementation, not
  settled here.
- **What `ASK` means changes once MyTelegramBot exists.** Today
  `PolicyResult.under(unattended=True)` collapses `ASK` to `DENY` because
  nothing can ask a human in CI. `TelegramPolicy` (MyTelegramBot's core
  export) wraps any `Policy` and gives `ASK` a real, bounded-timeout human
  channel — with the same fail-closed default (timeout/error → `DENY`) so
  the existing safety property never regresses, it just gets a chance to
  resolve to `ALLOW` first.
- **MySearcher / graphify synergy — now a real tool.** MySearcher's
  deterministic pre-work (naive token-overlap shortlisting) was flagged as
  a placeholder; MyGrapher is that upgrade. It deliberately never performs
  graphify's LLM-using initial build — only the LLM-free incremental
  `--update` path — so it can't smuggle a second Engine call into tools
  that consume it. It requires a graph to already exist (bootstrapped once
  by a human via `/graphify`), and refuses to bootstrap one itself.
- **Cross-tool code reuse isn't settled.** MyAdvisor wants MyKnowledger's
  and MySearcher's shortlist logic; MyKnowledger and MyReporter share
  ledger-merging. Two options: `My[X]` tools depend on each other as
  installed packages (like `my-guard` depends on `mythings-core`), or
  shared retrieval helpers get promoted into `mythings-core` once
  duplicated across ≥2 tools. Leaning toward the latter — it keeps the
  harness's "only shared dependency is core" property intact — but this
  isn't decided; each affected doc flags it rather than picking silently.
- **A repeated open question: reference scaffold vs. dedicated template
  repo.** Both MyScaffolder (copying a new tool's boilerplate) and
  MyDriftWatcher (defining "canonical" for drift comparison) independently
  raise the same question — copy from an existing tool repo, or maintain a
  separate `mythings-template`-style repo nothing ever deploys from. Likely
  the same answer should apply to both; not decided here.

## MyCoder (deferred)

The "act" tool — issue → diff → PR, i.e. writing the feature/fix itself
rather than a test, a comment, or a label. Package `mycoder`. Deferred
because its single Engine call ("write the diff for this issue") is the one
judgment step `NoopEngine` cannot meaningfully stand in for — a fixed-string
reply can't produce a working diff, so the tool can be *designed* now but
can't be *tested* end-to-end (happy path) until a real `Engine` backend
exists. Revisit once Phase 1 (real backends, cheapest-capable-first per
`ARCHITECTURE.md`) lands; at that point it inherits the same harness shape
as the other five, with `Workspace` + `Policy` doing the heaviest lifting
since it's the only tool that both edits code *and* needs the sandboxing
that implies.
