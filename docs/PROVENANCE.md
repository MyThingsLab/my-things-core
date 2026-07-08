# Build provenance — seeing a tool's whole history, start to ship

MyThingsLab's runtime thesis is the **ledger**: *append a structured outcome so
the next run can trust it.* This document applies that same idea one level up —
to the **building** of each `My[X]` tool — so that when a tool ships, the entire
development process is reconstructable from the first commit to the release.

## The four layers

Each answers a different question; only one links the others.

| Layer | Answers | Lifespan | Where it lives |
|---|---|---|---|
| Git commits / PRs / CI | *What* changed, exactly | forever | the repo |
| **Build ledger** (`dev-ledger/`) | *Why*, *when*, *which session* | forever | the repo |
| Session memory | Working context to resume next time | until superseded | the builder's machine |
| Session transcript | The raw *how* | archival | the builder's machine |

Git records *what* but never *why*, what was **rejected**, or **cross-session
continuity**. The build ledger fills that gap and is the **spine**: each entry
carries `data={commit, pr, session, ...}`, so one line jumps you to the exact
commit and PR. Reading `dev-ledger/` top-to-bottom is the whole story in a few
dozen structured lines instead of thousands of lines of transcript.

## The build ledger

It *is* `mythings.ledger` — we dogfood the runtime contract to record the repo's
own construction (which also battle-tests the schema before any tool depends on
it). Layout: **one JSONL file per build session** under `dev-ledger/`, so
concurrent branches never conflict; readers merge and sort by timestamp.

Schema (the standard `LedgerEntry`):

| Field | Build-ledger meaning |
|---|---|
| `tool` | always `claude-code` — the builder |
| `kind` | `scaffold` \| `build` \| `decision` \| `fix` \| `ship` |
| `outcome` | `success` \| `rejected` \| `superseded` |
| `detail` | one-sentence rationale — the *why* |
| `data` | `{session, commit, pr, files, supersedes}` |

`decision` entries are the point: they capture the reasoning git throws away
(e.g. *"StrEnum over (str, Enum) — ruff UP042 breaks CI on main"*).

## The per-session ritual

1. **Open** — read session memory and `python -m mythings._devledger show` to see
   exactly where the last session stopped and *why*.
2. **Work** — commit atomically, as usual.
3. **Close** — append ledger entries for milestones and decisions, refresh
   memory, commit `dev-ledger/`.

At release, tag the version and append a final `kind=ship` entry. Then `git log`
plus `dev-ledger/` reconstruct start→end — and because the ledger is in-repo, that
provenance ships *with the tool*.

## The helper

```bash
# append (session defaults to $CLAUDE_SESSION_ID / $MYTHINGS_SESSION / today)
python -m mythings._devledger add decision \
  --detail "chose X over Y because Z" --commit "$(git rev-parse --short HEAD)"

# read the whole trail, oldest first (optionally --session ID or --kind decision)
python -m mythings._devledger show
```

`_devledger` is deliberately a private module, not part of the `mythings`
contract surface — it is build tooling, available to every repo that installs
`my-things-core`. Automating the mechanical linkage (a `Stop` hook that stamps
commit shas + session id) is a deferred, opt-in step; today the ritual is manual.
