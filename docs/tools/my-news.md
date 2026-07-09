---
tool: MyNews
repo: my-news
package: mynews
status: designed
added: 2026-07-08
backlog_label: my-news
engine_call: write a digest from these newly discovered items
ledger_kinds: [news_digest]
depends_on: []
---

# MyNews — design plan

## Purpose

Given a standing subscription issue labeled `my-news` (a beat, e.g. "AI
research", "local city council"), on a recurring GitHub Actions
`schedule:` trigger discovers current sources live and posts a dated
digest comment summarizing what's new **since the last run**, cited.
Package `mynews`, backlog label `my-news`.

Same discovery shape as MyResearcher's `brief` mode (live search, cite
only what's retrieved, never fabricate) but time-boxed to "since
`last_run`" rather than "the definitive brief on a topic," and delivered
on a schedule rather than in response to a one-off ask. It is discovery +
digest, **not verification** — see MyKnowledger's `verify` subcommand for
checking a specific claim against a corpus.

## The single Engine call

Required: "from these discovered items published since `<last_run>`,
write a dated digest for this beat."

- **Input:** the subscription issue title + body, plus a
  deterministically retrieved, size-capped candidate list of items
  published after `last_run` (see pre-work). `context = {"topic_issue":
  N, "since": timestamp, "item_count": k}`.
- **Output:** `data = {"headline_summary": str, "items": [{"source_id",
  "title", "one_liner"}]}` — the model may only cite `source_id`s from
  the given candidate list, same discipline as MyResearcher/MyKnowledger.
- Against `NoopEngine`: no synthesis — the raw filtered item list with no
  summary, same honest degrade as MyResearcher's `brief`.

## Deterministic pre-work

1. Read the subscription issue (label `my-news`).
2. Read the topic's last `kind=news_digest` ledger entry for `last_run`
   (default: 7 days ago on first run).
3. Retrieve over the same **LLM-free HTTP** boundary MyResearcher uses:
   RSS feeds (keyless, zero-config default, mirroring MyResearcher's
   arXiv-first choice) plus the configured web-search provider if its
   secret is set. Normalize/dedupe and filter to items published after
   `last_run`; cap to a fixed top N (same size-cap discipline as every
   retrieval tool in the line).
4. If nothing new since `last_run`, **skip the Engine call** and post
   "nothing new for `<beat>` since `<last_run>`" — deterministic
   short-circuit, same shape as MyKnowledger's no-match case, but the
   ledger's `last_run` still advances to "now" so the next scheduled run
   doesn't re-check the same window.

## Ledger

- **Writes:** `kind=news_digest`, `outcome=success|skipped`,
  `detail`="digest for `<beat>` (`k` items)", `data={topic_issue,
  last_run, new_last_run, cited, comment_url}`.
- **Reads:** the topic's last `kind=news_digest` entry, to compute
  `last_run` for this run.

## Guard & Workspace

Comment-only by default — `ALLOW` by default, no `Workspace`, no PR, same
side-effect shape as MyKnowledger/MyReporter. An optional `--commit` mode
additionally writes `news/<date>-<topic>.md` via `Workspace` and opens a
PR (`Closes` nothing — it's a recurring log, not tied to a single issue
close) for an archived record; same never-merges discipline as every
other `Workspace`-using tool.

**First tool in this batch whose primary trigger is a recurring
`schedule:` rather than an issue being opened.** `ARCHITECTURE.md` already
sanctions GitHub Actions `schedule:` as "the conductor" instead of a
daemon — MyNews is the first doc to actually exercise that, not introduce
a new capability.

## CLI surface

```
mynews digest --issue <number> [--commit] [--sources rss,web]
```

Invoked by a `schedule:` trigger in the subscription issue's own repo
workflow (daily/weekly, per the beat), not run interactively as its
normal path — same "first live-web tool besides MyTelegramBot" secret
discipline as MyResearcher: the web-search provider's key is a CI secret,
never committed; RSS needs no key.

## Test plan

- **Happy path:** mocked RSS/web HTTP returning items after a fixture
  `last_run`; scripted `Engine` digest; assert the comment renders the
  summary + cited items, `new_last_run` advances, and
  `kind=news_digest`/`outcome=success` is written.
- **Edge case (nothing new):** mocked HTTP returns only items before
  `last_run`; assert the Engine is never called (spy `Engine`),
  `outcome=skipped`, the "nothing new" comment posts, and `last_run`
  still advances.
- **`--commit` mode:** assert `news/<date>-<topic>.md` is written and a
  PR opens, same fixture-tree style as MyResearcher's committed-brief
  test.
- Mock the RSS/web HTTP boundary and `github.Runner`; retrieval filtering
  and digest rendering run against real fixtures. One live-network smoke
  test is `@pytest.mark.slow`.

## Dependencies & build order

Same retrieval-layer shape as MyResearcher (stdlib HTTP, pluggable
provider secret) — natural to build alongside or after it, reusing its
provider-config pattern rather than re-deciding it. Depends on core
`ledger`, `github`, `policy`, optionally `isolation` for `--commit` mode.
Independent of MyKnowledger/MyUni/MyProfessor.

**Open questions:**

- **RSS vs. web-search-provider-only.** Recommend RSS as the zero-config
  default (keyless, like MyResearcher's arXiv default); the web-search
  provider adds sources RSS alone would miss, once its secret is wired.
- **One beat per issue, or multiplexed feeds/queries per issue?** v0:
  one topic per issue, same granularity as MyResearcher's per-topic
  issues; a beat wanting several feeds is several issues for now.
- **Schedule cadence is per-repo-workflow, not per-issue** — a `my-news`
  label alone doesn't carry its own cadence; whether that should become a
  structured issue field (`cadence: daily`) read by the workflow, or stay
  a human decision when wiring the `schedule:` cron, is not decided.
