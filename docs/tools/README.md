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
| MyOrchestrator | picks the single next unit of work across the whole fleet | optional: "break a tie among top candidates" | [my-orchestrator.md](my-orchestrator.md) |
| MyTester | writes a test for one uncovered unit | "write a test for this one uncovered unit" | [my-tester.md](my-tester.md) |
| MyReporter | digests Ledger + dev-ledger into a report | none (optional prose summary) | [my-reporter.md](my-reporter.md) |
| MySearcher | ranks files relevant to an issue | "rank relevant files for this task" | [my-searcher.md](my-searcher.md) |
| MyReviewer | flags correctness bugs on an open PR | "does this diff have a correctness bug?" | [my-reviewer.md](my-reviewer.md) |
| MyGroomer | labels/splits raw issues into ready units | "split/label this issue" | [my-groomer.md](my-groomer.md) |
| MyTelegramBot | pushes ledger notifications; relays `Policy` `ASK` to a human over Telegram | none | [my-telegram-bot.md](my-telegram-bot.md) |
| MyScaffolder | bootstraps a new My[X] tool repo from a proposal | "expand a proposal into the four CLAUDE.md seams" | [my-scaffolder.md](my-scaffolder.md) |
| MyWiki | answers "what happened / why" from *this project's own* ledger history | "answer this question using only these ledger excerpts" | [my-wiki.md](my-wiki.md) |
| MyKnowledger | answers domain questions from *external* literature (papers/books/web) | "answer this question using only these knowledge-graph excerpts" | [my-knowledger.md](my-knowledger.md) |
| MyResearcher | discovers external sources live (web + arXiv), writes a cited study brief; orders topics into a study path | "write a study brief from these discovered sources" / "order these researched topics" | [my-researcher.md](my-researcher.md) |
| MyAdvisor | recommends a course of action with trade-offs | "recommend an answer, with trade-offs" | [my-advisor.md](my-advisor.md) |
| MyChangelogger | turns ship/fix ledger entries into a CHANGELOG.md section | none | [my-changelogger.md](my-changelogger.md) |
| MyTodo | curates a TODO.md (per-repo or org-wide roll-up) from open issues + MyPlanner's plan | optional: "prioritise issues into Now/Next/Later" | [my-todo.md](my-todo.md) |
| MyDriftWatcher | flags cross-repo convention drift | none | [my-drift-watcher.md](my-drift-watcher.md) |
| MyGrapher | keeps a repo's knowledge graph fresh for other tools to query | none | [my-grapher.md](my-grapher.md) |
| MyDescriber | writes/improves a PR's title + description after it's opened | "write a PR title + description for this diff" | [my-describer.md](my-describer.md) |
| MyProjector | keeps the fleet's GitHub Project board + tracking issues synced to live repo state | optional: "rewrite this card's last/next-step summary" | [my-projector.md](my-projector.md) |
| MyPlanner | produces a priority-ordered, multi-item plan across the whole backlog | required: "propose a sequence, with rationale" | [my-planner.md](my-planner.md) |
| MySite | drafts content/design changes for a personal Jekyll site (default: `lorenzoliuzzo/lorenzoliuzzo.github.io`) | "draft the Jekyll content for this request" | [my-site.md](my-site.md) |
| MyDocs | keeps the fleet's technical-docs site (`mythingslab.github.io`) in sync with each tool's README/CLAUDE.md | "write/update this tool's docs page from its README + seams" | [my-docs.md](my-docs.md) |
| MyTypster | drafts and compiles a document as typeset Typst source + PDF | "draft the Typst source for this content request" | [my-typster.md](my-typster.md) |
| MyPresentation | drafts a slide-by-slide talk outline, then renders it via MyTypster | "draft the slide outline + speaker notes" | [my-presentation.md](my-presentation.md) |
| MyUni | decomposes a field of study into a curriculum, opening one issue per topic for MyResearcher | "decompose this field into an ordered curriculum" | [my-uni.md](my-uni.md) |
| MyProfessor | teaches or quizzes on a topic already in MyKnowledger's corpus | "write a lesson" / "grade this answer" | [my-professor.md](my-professor.md) |
| MyNews | discovers current sources on a schedule and posts a dated digest since the last run | "write a digest from these newly discovered items" | [my-news.md](my-news.md) |
| MyCoder | issue → diff → PR (the "act" tool) | deferred | see stub below |

## Recommended build order

0. **MyOrchestrator** — build before everything below, including MyTester.
   It's the only tool with zero dependency on any other `My[X]` tool, and
   it exists precisely to replace *this list* (a build order decided once,
   in conversation) with a live, re-computed answer to "what next" —
   see its doc for why that matters while only one worker (the
   interactive session) can act on any of this.
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
15. **MyProjector** — added 2026-07-07, proposed by the user directly
    after watching a whole session of manual GitHub Project board
    bookkeeping. Independent of every other `My[X]` tool (only needs core
    `ledger`/`policy` + the new `mythings.projects` module), so it could
    build early like MyOrchestrator/MyReporter — but it's gated on that
    new core module landing first, which is the real constraint on timing,
    not tool ordering.
16. **MyPlanner** — added 2026-07-07 alongside MyProjector, in response to
    the same session. Hard-depends on MyOrchestrator's `manifest.json`
    (already shipped, so buildable now) and soft-depends on MyProjector
    (degrades gracefully if built first). Build after MyProjector if
    sequencing by convenience; not blocked on it either way.
17. **MySite** — added 2026-07-08, proposed by the user directly (a
    recurring content/design tool for their personal site, distinct from
    ordinary fleet feature work). Zero dependency on any other `My[X]`
    tool — no new core method needed (`github.open_pr` and `isolation.
    Workspace` already cover its one side effect). Standalone; build any
    time.
18. **MyDocs** — added 2026-07-08 alongside MySite, same session. Depends
    only on other `My[X]` tools already existing to have something to
    document and on `mythingslab.github.io`'s genesis content existing to
    write into — not on MySite (different target repo, no shared code).
    Build after at least a couple of tools have shipped READMEs worth
    publishing.
19. **MyTypster** — added 2026-07-08, from a user batch of 15 tool ideas
    (see the cross-cutting note below on how that batch was triaged).
    Zero dependency on any other `My[X]` tool, but needs the `typst` CLI
    added to the CI image (new toolchain dependency, confirm first) and
    the public-repo/PII open question resolved before it drafts anything
    containing personal data. Build any time once that's settled —
    **MyPresentation hard-depends on it**, so build it first between the
    two.
20. **MyPresentation** — added 2026-07-08, same batch. Depends on
    MyTypster for compilation; build after it.
21. **MyUni** — added 2026-07-08, same batch. Needs the same
    `create_issue`/`add_labels` core batch MyGroomer needs (§ Core
    additions in [BUILD_GUIDE.md](BUILD_GUIDE.md)) — build after that
    lands. Soft-depends on MyResearcher existing to consume what it opens.
22. **MyProfessor** — added 2026-07-08, same batch. Depends on
    MyKnowledger's retrieval pattern and pre-bootstrapped corpus; build
    after MyKnowledger.
23. **MyNews** — added 2026-07-08, same batch. Same retrieval-layer shape
    as MyResearcher; build alongside or after it, reusing its
    provider-config pattern. First doc whose primary trigger is a
    `schedule:` cron rather than an opened issue.

## Cross-cutting notes

- **MyOrchestrator addresses a real bootstrapping gap, without becoming a
  daemon.** [`ARCHITECTURE.md`](../ARCHITECTURE.md) states "no
  scheduler/daemon — GitHub Actions `schedule:`/event triggers are the
  conductor," which holds once a real `Engine` backend lets CI run judgment
  steps unattended. Until then, that conductor role has no automated
  substitute — the single interactive Claude session is the only worker,
  and prioritizing across 15 tools' backlogs has been happening ad hoc, in
  conversation. MyOrchestrator is still a one-shot CLI (`myorchestrator
  next`), not a daemon — it doesn't violate the principle, it just makes
  the single-worker interim explicit and re-computable instead of
  memory-dependent.
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
- **MyResearcher is discovery, not retrieval.** MyKnowledger *answers* from a
  corpus a human already built; MyResearcher *goes and finds* the sources live
  (web + arXiv) and writes a cited study brief — the opposite direction of the
  same literature domain. It is the **second tool to touch a live external
  service** after MyTelegramBot (a web-search provider's API, plus keyless
  arXiv), so it inherits the same "new CI secret, confirm before implementing,
  mock the boundary in the default suite" discipline. It never ingests a corpus
  itself (the same fence MyKnowledger/MyGrapher hold) — it can only *hand a human*
  a source list to graphify out of band, which is what could later feed
  MyKnowledger. Its `plan` mode orders *external study topics*, distinct from
  my-planner's *fleet-backlog* sequencing (different corpus, different ledger
  `kind`); promote a shared "order-a-set" helper to core only if a third caller
  appears.
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
- **MySite is the fleet's first tool whose target repo lives outside the
  MyThingsLab org.** Every tool's target repo has always been configurable
  at run time per `ARCHITECTURE.md`; MySite is the first to actually point
  it at a personal repo (`lorenzoliuzzo/lorenzoliuzzo.github.io`) rather
  than a fleet repo. No new capability is needed for this — it's confirmed
  proof the existing design already generalizes past the org boundary.
- **Two of the 2026-07-08 batch's fifteen proposed names turned out to be
  existing tools by another name, not new ones.** "my-designer" (recommend
  product/design decisions) is MyAdvisor's exact shape over a different
  question domain — folded into [my-advisor.md](my-advisor.md) rather
  than shipped as a sixth "retrieve, then recommend" tool. "my-fact-check"
  (verify a claim against sources) is MyKnowledger's exact "retrieve, then
  the model may only cite the given excerpts" shape, phrased as a claim
  instead of a question — added as MyKnowledger's `verify` subcommand
  rather than a sixth standalone corpus-citing tool (see the "Cross-tool
  code reuse isn't settled" note above, now doubly confirmed: catching
  the collision *before* drafting a doc is cheaper than catching it after).
- **MySite and MyDocs are both content-publishing tools with no shared
  code.** They look superficially similar (draft Jekyll content, open a
  PR) but point at different corpora (a free-form content request vs. a
  tool's own README/CLAUDE.md) and different destinations (a personal site
  vs. the fleet's docs site) — same "don't couple two tools over a
  surface-level shape match" discipline as MyWiki vs. MyKnowledger.
- **Decision authority across MyOrchestrator / MyPlanner / MyProjector —
  resolved 2026-07-07.** Adding two more fleet-wide tools risked three
  sources of truth disagreeing about "what happens next." The line:
  - **MyOrchestrator** is the single source of truth for *the next
    action*. Short-horizon, mostly deterministic, one Engine call only to
    break a genuine tie. Nothing else picks or dispatches work.
  - **MyPlanner** produces a longer-horizon *sequence with rationale* and
    feeds it into MyOrchestrator's ranking as one more signal — the same
    role its existing `kind=drift`/`kind=ask` urgency boosts already play.
    MyPlanner never picks or dispatches directly, mirroring MyOrchestrator's
    own "recommends, doesn't invoke another tool's CLI" stance one level up.
  - **MyProjector** makes no priority judgments at all — pure bookkeeping,
    syncing dashboard/tracking-issue state to match what already happened.
  - This also answers a fourth idea raised in conversation: a dedicated
    agent to decide *when it's time to build a particular unbuilt tool*.
    **Not a separate tool** — that decision already belongs to
    MyOrchestrator (its existing dependency-readiness check + ranking over
    `manifest.json`, per its own doc's steps 3-4), just enriched once
    MyPlanner's pacing signal exists to boost/penalize candidates the same
    way urgency signals already do. A fourth tool here would just be a
    second, competing implementation of MyOrchestrator's own job.

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

**"my-renderer" (2026-07-08) is a candidate MyCoder target, not a tool of
its own.** Proposed by the user as "an example of high-difficulty codebase
that can be implemented with the fleet" — i.e. a deliberately hard build
(a renderer, a compiler, whatever's chosen) meant to stress-test the
fleet's ability to build real software, not a My[X] fleet-management bot.
It has no issue-driven shape, no single narrow Engine call, no ledger
`kind` of its own — it's *work for MyCoder to do* once MyCoder exists,
the same way any other feature request would be. Revisit choosing a
concrete target once MyCoder is real.

## Parked: personal continuous-service tools (2026-07-08)

The same user batch that produced MyTypster/MyPresentation/MyUni/
MyProfessor/MyNews above also proposed six more: **my-filemanager**
(manage files under `home`), **my-drive** (archives), **my-music**
(freely listen to music), **my-photos** (Immich integration), **my-mood**,
and **my-sleep** (quality tracking, possibly wearable integration).

None of these fit the batch's shared contract — GitHub issue triggers one
deterministic pre-step, one narrowly-scoped Engine call, a PR/comment,
`Policy`/`Guard` in between, no daemon. They're **always-on personal
services or integrations** instead: real external accounts/OAuth (Immich,
a wearable's API), continuous data ingestion outside any git repo, and in
my-mood/my-sleep's case, personal health data — a materially different
sandboxing and secrets story than "a bot that reacts to GitHub issues."

Deliberately **not drafted as docs here** — forcing them into the
issue/PR shape would be a bad fit, and the fleet has no confirmed contract
yet for "always-on personal service with external credentials," which is
exactly the kind of architectural addition the workspace's
architectural-change rule says to propose and confirm *before* any
consuming tool's build starts, not accrete tool-by-tool. Revisit as a
deliberate design conversation (what would that contract even look like
in `mythings-core`?) before writing design docs for any of these six.
