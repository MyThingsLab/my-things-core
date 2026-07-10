---
tool: MyGuide
repo: my-guide
package: myguide
status: designed
added: 2026-07-09
backlog_label: my-guide
engine_call: required: match a plain-language wish to the fleet catalog
ledger_kinds: [guide_catalog_rendered, guide_wish_matched, guide_trial_enqueued]
depends_on: [tool:my-server, tool:my-telegram-bot]
---

# MyGuide — design plan

## Purpose

The fleet's front door for someone who has never opened a terminal. A new
tester — a friend, a parent — asks "what is this, and what can it do for
me?", and MyGuide answers in their language, then lets them safely watch
one tool actually run. Package `myguide`, backlog label `my-guide`.

Two jobs, one catalog:

- **`catalog`** — renders one plain-language card per *shipped* tool: what
  it is for, what it reads, what it produces, and what it will never
  touch. Deterministic; no Engine call.
- **`wish`** — takes a free-text wish ("I want to know what's in my book
  folder") and matches it to the tools that could serve it, with a
  dry-run narration of exactly what would happen.

A matched wish can then be **tried** — but only against a dedicated
playground repo, never the live fleet (see *Blast radius*).

This is deliberately not a second `my-docs`. `my-docs` publishes a
reference page per tool for someone who already knows what a CLI is;
`my-dashboard` renders CI and issue status for someone who already knows
what CI is; `my-wiki` answers "what happened" from ledger history. None of
them answers "what can this do *for me*", which is the only question a
newcomer has.

## The single Engine call

Required, in `wish`: "match this plain-language wish to the fleet catalog."

- **Input:** the wish text, plus the deterministically assembled catalog
  (one entry per shipped tool: name, plain gloss, reads, produces,
  never-touches). `context = {"wish": str, "catalog": [...]}`.
- **Output:** JSON `{"understood": str, "matches": [{"tool": str, "why":
  str, "confidence": "high|low"}], "unsupported": bool,
  "clarifying_question": str|null}`.
- `matches[].tool` may only name a tool present in the given catalog —
  the same cite-only-what-you-were-given discipline as MyIdea/MyResearcher.
  A wish the fleet cannot serve must come back `unsupported: true` with an
  honest "nothing here does that", never a nearest-neighbour guess.
- The Engine **never** writes the tool descriptions. It only *selects*
  among descriptions a human already curated (see `phrasebook.toml`), so a
  newcomer can never be told the fleet does something it does not do.
- Against `NoopEngine`: keyword-match the wish against the catalog and
  render the hits with an explicit "no judgment engine attached" note.

## Deterministic pre-work

1. Load the fleet catalog from `tools_manifest.json`, the canonical registry,
   which ships as package data inside `mythings`. Keep `status: shipped` for
   the cards; keep **every** repo, whatever its status, for the blast-radius
   denylist below.

   Read the manifest, **not** `docs/tools/*.md` frontmatter: several shipped
   tools (`my-guard`, `my-server`) have no design doc at all, so the doc set
   under-reports the fleet — and an omission in the denylist would let a live
   repo pass as a playground. Read the data file, never the private
   `mythings._manifest` module (core's `__all__` is contracts-only).
2. Join each shipped tool against `phrasebook.toml` — this repo's curated,
   human-reviewed, plain-language layer:

   ```toml
   [my-archivist]
   gloss    = "Tidies a folder of books: tells you what you own, finds duplicates, fills in missing authors."
   reads    = "the names of files in a folder you choose"
   produces = "a list, sent back to you"
   never    = "opens, moves, renames, or deletes a single file"
   ```

3. A shipped tool with no phrasebook entry renders under **"Not yet
   explained"** — never silently dropped (MyDashboard's `Unshelved`
   invariant). A phrasebook entry naming a tool that is absent or not
   shipped is a **hard error**, so the plain-language layer cannot drift
   into describing tools that do not exist.

The engineer-facing `title` from the manifest is never shown to a tester;
it is only used to detect drift between the two layers.

## Blast radius

A tester pressing "try it" must never spend tokens on, or add noise to, a
live fleet repo.

- `myguide trial --tool X` renders the dry-run narration — `reads`,
  `produces`, `never` — straight from the phrasebook. Deterministic, no
  Engine call, no side effect. **This is the default.**
- `myguide trial --tool X --for-real` enqueues one labeled backlog issue
  into the playground repo by calling **MyServer's existing gated write**
  (`POST /tools/<name>/issues`). MyGuide adds **no write path of its own**
  and never opens a PR.
- Fail-closed: `MYGUIDE_PLAYGROUND_REPO` unset → refuse. If the resolved
  target repo appears anywhere in the fleet manifest, **refuse** — the
  playground is by construction not a fleet repo.
- Every enqueue is an `Action` through `Policy`; an unattended `ASK`
  collapses to `DENY` as everywhere else.

A tester who gets stuck presses "this confused me", which enqueues a
`my-guide`-labeled issue into that same playground repo through that same
single write. Closing the tester-feedback loop costs no new machinery.

## Transport

The renderer is transport-agnostic: `render_catalog()` and `render_trial()`
return a `Message` (title, lines, choices), and a transport decides how to
show it. `--transport stdout` is the Verify seam; `--transport telegram`
delivers through MyTelegramBot's existing push + inline-button +
`poll_decision` machinery, so a tester answers by **pressing a bounded
choice**, exactly as a `Policy` `ASK` is answered today.

**Explicit non-goal in v0: an always-on inbound chat daemon.** Free-text
`wish` is served at the CLI, and over Telegram as a pre-seeded menu of
wishes rendered as buttons. A bot that listens for arbitrary inbound chat
is an *always-on personal service* — the shape this doc set has already
parked (see [README.md](README.md), "Parked: personal continuous-service
tools"), pending a deliberate `my-things-core` contract for it. Building
that contract is a prerequisite, not a detail to accrete here.

Because the renderer is transport-agnostic from day one, the later web
view is a `myserver` route over the same `Message` — not a rewrite.

## Ledger

- **Writes:** `kind=guide_catalog_rendered`, `data={tools, unexplained}`;
  `kind=guide_wish_matched`, `data={wish, matches, unsupported}`;
  `kind=guide_trial_enqueued`, `data={tool, playground_repo, issue_url}`.
- **Reads:** none beyond its own history.

## Guard & Workspace

No `Workspace` — MyGuide never edits code and never opens a PR. Its only
side effect is the delegated playground enqueue, routed through `Policy`.
`--transport stdout` with the default (dry-run) `trial` touches nothing.

## CLI surface

```
myguide catalog [--transport stdout|telegram]
myguide wish "<plain language>" [--engine noop|claude-cli]
                                [--transport stdout|telegram]
myguide trial --tool <name> [--for-real] [--transport stdout|telegram]
myguide check                # phrasebook vs. manifest drift; exit 1 if stale
```

`check` is the mechanical gate behind the "never describe a tool that does
not exist" rule, and belongs in this repo's CI.

## Test plan

- Happy path: scripted `Engine` returning two matches; assert the rendered
  card set carries gloss/reads/produces/never, and `guide_wish_matched` is
  written.
- Edge (fabrication): `Engine` names a tool absent from the catalog →
  raise, render nothing, record the failure honestly.
- Edge (`NoopEngine`): only keyword-matched hits render, with the
  no-engine note; no fabricated gloss.
- Edge (unsupported wish): `unsupported: true` renders "nothing here does
  that" plus the clarifying question — never a nearest match.
- Blast radius: `trial` without `--for-real` performs no write;
  `--for-real` with `MYGUIDE_PLAYGROUND_REPO` unset refuses; with it set to
  a repo present in the manifest, refuses.
- Drift: a phrasebook entry for an unshipped tool fails `check`; a shipped
  tool with no entry renders under "Not yet explained".
- Denylist completeness: a shipped tool that has **no design doc**
  (`my-server`) is still refused as a playground target.
- `Policy` `DENY` / unattended `ASK`: narration prints, nothing enqueues.

## Dependencies & build order

Core `ledger`, `policy`, `engine`, `github`; `my-guard`. Delegates its one
write to **`my-server`** and its Telegram delivery to
**`my-telegram-bot`** — both shipped, so MyGuide is **buildable now**.
Reads the catalog `my-docs` already publishes; adds no new core contract.

**Open questions:**

- The catalog reads the `tools_manifest.json` **data file** shipped inside
  `mythings`, rather than importing `mythings._manifest`, which is
  deliberately build tooling and not exported (core's `__all__` is
  contracts-only). That leaves MyGuide depending on a package-data path that
  is not a public contract. Since a safety property (the blast-radius
  denylist) now rests on it, promote a public read-only `mythings.manifest`
  in one deliberate core PR — and until then, do **not** let any tool reach
  into the private module.
- Free-text inbound over Telegram needs an "inbound command" contract
  before it can exist. Worth designing on its own, together with the six
  parked personal-service tools that need the same thing.
- Should the playground repo be per-tester (isolation, easy reset) or one
  shared sandbox (simpler, testers see each other's runs)? Recommend one
  shared sandbox in v0; revisit if a tester's run confuses another's.
