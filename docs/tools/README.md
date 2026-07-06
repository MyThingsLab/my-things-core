# My[X] tool designs — index

Design docs for the next tools in the MyThingsLab line, all buildable now
against `NoopEngine` (zero tokens), per the harness in
[`../../src/mythings/harness.md`](../../src/mythings/harness.md) and the
seams explained in [`../CONVENTIONS.md`](../CONVENTIONS.md). Each doc below
is self-contained; this page only orders and connects them. For the
step-by-step *how* of turning a doc into a shipped repo, see
[BUILD_GUIDE.md](BUILD_GUIDE.md). Repo layout: **one repo per tool**,
confirmed — matching the existing `my-guard` convention, no monorepo. New
tools scaffold from [mythings-template.md](mythings-template.md), a
dedicated (not-a-tool) template repo — build that before MyScaffolder.

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
| MyWiki | answers "what happened / why" from *this project's own* ledger history | "answer this question using only these ledger excerpts" | [my-wiki.md](my-wiki.md) |
| MyKnowledger | answers domain questions from *external* literature (papers/books/web) | "answer this question using only these knowledge-graph excerpts" | [my-knowledger.md](my-knowledger.md) |
| MyAdvisor | recommends a course of action with trade-offs | "recommend an answer, with trade-offs" | [my-advisor.md](my-advisor.md) |
| MyChangelogger | turns ship/fix ledger entries into a CHANGELOG.md section | none | [my-changelogger.md](my-changelogger.md) |
| MyDriftWatcher | flags cross-repo convention drift | none | [my-drift-watcher.md](my-drift-watcher.md) |
| MyGrapher | keeps a repo's knowledge graph fresh for other tools to query | none | [my-grapher.md](my-grapher.md) |
| MyDescriber | writes/improves a PR's title + description after it's opened | "write a PR title + description for this diff" | [my-describer.md](my-describer.md) |
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
8. **MyWiki** — reuses MyReporter's ledger-merging logic; build after it.
   Independent of MySearcher/MyGrapher for v0 (keyword match is enough).
9. **MyGrapher** — build after MySearcher: its purpose is retrofitting
   MySearcher's (and later MyReviewer's) naive shortlist step with a real
   graph query, so MySearcher needs to exist first to have something worth
   retrofitting.
10. **MyKnowledger** — build alongside or right after MyGrapher: both share
    the "requires a pre-bootstrapped `graphify-out/`, never bootstraps it
    itself" invariant and the same mocked-CLI test style, over two
    different corpora (code vs. external literature). Needs a
    pre-bootstrapped external-knowledge graph, built out of band by a
    human, before it's testable end to end.
11. **MyScaffolder** — meta relative to every other tool; doesn't pay off
    until several more tool proposals are queued. Build once that backlog
    exists, not first.
12. **MyDriftWatcher** — low urgency while only 2-3 repos exist; drift only
    matters once there's enough repos to diverge. Most valuable once
    MyScaffolder is producing new repos regularly.
13. **MyAdvisor** — last: depends on both MyWiki's and MySearcher's
    shortlist logic, and its judgment quality can't be meaningfully
    validated against `NoopEngine` (same limitation as MyCoder).
14. **MyDescriber** — build after MyReviewer (shares `diff()` and the
    draft/docs-only skip logic) and after MyWiki (reuses its shortlist).
    It's the tool that lets every PR-opening tool's default body stay
    minimal, so later it's worth revisiting MyTester's and MyChangelogger's
    docs to confirm their bodies don't duplicate what MyDescriber now owns.

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
  MyKnowledger shares this exact invariant over a second, separate
  graphify corpus (external literature instead of the repo) — the "never
  bootstraps, only queries" rule generalizes to any tool wrapping graphify.
- **MyWiki vs. MyKnowledger — two corpora, one shape.** Early drafts named
  the ledger-history Q&A tool "MyKnowledger"; it's renamed **MyWiki** so
  "MyKnowledger" is free for what it should actually mean: domain knowledge
  from *external* sources (papers, books, the internet), not this
  project's own history. Both tools do the identical "retrieve a
  shortlist, then one Engine call that may only cite from it" shape — they
  just point at different corpora (project ledger vs. an external
  literature graph) — and both write distinct ledger `kind`s (`wiki` vs.
  `knowledge`) so their entries never collide.
- **Cross-tool code reuse isn't settled.** MyAdvisor wants MyWiki's and
  MySearcher's shortlist logic; MyWiki and MyReporter share ledger-merging.
  Counting MyKnowledger, **five** tools now independently implement
  "shortlist from a corpus, then cite" (MyWiki, MySearcher, MyAdvisor,
  MyDescriber, MyKnowledger) — a stronger signal than before that this
  shape deserves either a shared core helper or a settled reuse mechanism.
  Two options: `My[X]` tools depend on each other as installed packages
  (like `my-guard` depends on `mythings-core`), or shared retrieval helpers
  get promoted into `mythings-core` once duplicated across ≥2 tools.
  Leaning toward the latter — it keeps the harness's "only shared
  dependency is core" property intact — but putting RAG-specific shape
  into a dependency-free SDK deserves its own discussion; not decided here,
  each affected doc flags it rather than picking silently.
- **Resolved: dedicated template repo, not copy-from-existing-tool.**
  MyScaffolder and MyDriftWatcher independently raised the same question;
  see [mythings-template.md](mythings-template.md) — a standalone,
  never-deployed `MyThingsLab/mythings-template` repo is now the single
  canonical source both tools depend on. It isn't a `My[X]` tool itself
  (no Engine call, not issue-driven) and isn't in the build order below;
  create it before MyScaffolder or MyDriftWatcher's build starts.
- **PR descriptions are a separate concern from opening a PR.** MyDescriber
  enriches an already-open PR's title/body rather than every PR-opening
  tool (MyTester, MyChangelogger, eventually MyCoder) each generating its
  own prose. The convention this implies: a PR-opening tool's Engine call
  should stay scoped to its actual job (writing a test, formatting a
  changelog section) and its default PR body should stay minimal — issue
  link + a checklist — leaving curated prose to MyDescriber. Not
  retrofitted into MyTester's/MyChangelogger's existing docs here, but
  worth confirming when either is picked up for implementation.
- **`github.GitHub.diff()` now has two callers** (MyReviewer, MyDescriber),
  which is a stronger signal than either doc alone that it belongs in core
  sooner rather than later — still a confirm-before-implementing change,
  not decided by accretion.

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
