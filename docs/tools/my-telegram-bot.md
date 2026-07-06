# MyTelegramBot — design plan

## Purpose

Bridges the harness to the user over Telegram: pushes ledger notifications,
and turns a `Policy` `ASK` decision into a real synchronous human
confirmation instead of collapsing to `DENY` under an unattended runner.
Package `mytelegrambot`, backlog label `my-telegram-bot`.

## The single Engine call

None — deterministic. This is a plumbing/comms tool, not a judgment tool;
it relays existing `Action`/`Ledger` data verbatim, it never composes prose
that could hallucinate over what it's relaying.

## Deterministic pre-work

1. Load `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from environment — never
   logged, never written to the ledger.
2. **Notify path:** read the `Ledger`'s entries since this tool's own last
   `kind=notify` entry (same incremental pattern as MyReporter's
   "since last report"); format each as a one-line Telegram message.
3. **Ask path:** format an `Action` (`kind` + `payload`) as a human-readable
   message with inline Allow/Deny buttons — no model needed, it's a
   template over structured data already in hand.
4. Both paths call the Telegram Bot API over plain HTTPS
   (`urllib.request` + `json`, stdlib only) — no `python-telegram-bot` SDK,
   consistent with "shell out, don't pull SDKs" (here there's no `gh`/`git`
   equivalent to shell out to, so stdlib HTTP is the substitute).

## Ledger

- **Writes:**
  - `kind=notify`, `outcome=success`, `detail`="pushed digest for <window>",
    `data={window_start, window_end, message_id}`.
  - `kind=ask`, `outcome=allowed|denied|timeout`, `detail`=one-line action
    summary, `data={action_kind, action_payload, telegram_message_id,
    decision}`.
- **Reads:** its own last `kind=notify` entry (incremental push window).
  Never reads `kind=ask` history — every ask is independent, no dedupe.

## Guard & Workspace

- No `Workspace` — no code edits, no PR opened by this tool ever.
- **This tool *is* a `Policy` decorator, not a new contract.** It wraps an
  inner `Policy` (typically MyGuard's `Guard`):
  `TelegramPolicy(inner: Policy, bot_token, chat_id, timeout=300)`.
  `evaluate()` delegates to `inner.evaluate()`; if the result is `ASK`, it
  sends the Telegram prompt and blocks (bounded by `timeout`) for a reply,
  resolving to `ALLOW` or `DENY` from the human's answer. `ALLOW`/`DENY`
  from the inner policy pass through untouched — MyTelegramBot only adds a
  real channel for the `ASK` case, it never overrides a firm `DENY`.
  **Invariant: on timeout, no reply, or any Telegram API error, resolve
  `DENY`.** Fail-closed is non-negotiable — this tool must never turn a
  silent failure into an `ALLOW`.
  The tool's own network call to the Telegram API is itself a system
  boundary (mocked in tests), not something routed through `Policy` — it
  isn't a git/gh side effect the harness's default rules are about.

## CLI surface

```
mytelegrambot notify [--since ISO8601]
mytelegrambot ask --action-kind <kind> --payload-json <json> [--timeout 300]
```
Primarily consumed as a library (`TelegramPolicy` wrapping any `Policy`)
inside another tool's runtime, not just invoked standalone — the CLI form
above is for manual/CI-script use (e.g. a workflow step that notifies on
`kind=ship`).

## Test plan

- **Happy path:** inner `Policy` returns `ASK`; a fake Telegram HTTP
  transport (mocked boundary) replies "Allow" within the timeout; assert
  `TelegramPolicy.evaluate()` returns `ALLOW` and ledger gets `kind=ask,
  outcome=allowed`.
- **Edge case (timeout):** fake transport never replies; assert the call
  resolves `DENY` after the configured timeout (not hangs, not `ALLOW`) and
  ledger gets `outcome=timeout`.
- Mock only the Telegram HTTP boundary; `Policy`/`Action` objects are real.

## Dependencies & build order

Depends on core `policy` (implements/wraps `Policy`) and `ledger`. No
dependency on `github`, `engine`, or `isolation` — this tool never touches
git or a model. Independent of the other five tools; can be built any time,
but it's most useful once at least one tool (MyTester) can actually trigger
an `ASK` in practice, so build it after MyTester if sequencing by payoff.

**Open questions:**
- **Secrets in CI:** `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` need to live in
  GitHub Actions secrets for unattended runs — that's a CI/config change,
  explicitly out of scope for this design-only session; flagged, not done.
- **New dependency category:** every existing tool only ever talks to
  GitHub. This is the first that calls a third-party service — worth a
  deliberate go/no-ago before implementation, per the workspace CLAUDE.md's
  "adding a dependency" escalation rule, even though the HTTP call itself
  is stdlib-only.
- Whether `TelegramPolicy` should retry a dropped Telegram API call before
  falling back to `DENY`, or fail closed immediately — assumed immediate
  fail-closed for v0 (simpler, and consistent with "never silently pass").
