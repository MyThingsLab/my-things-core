# MyThingsLab service harness — rules for any long-running My[X] service

You are an agent developing a MyThingsLab **service** — a long-running process
(`my-server`, `my-telegram-bot`, `my-dashboard`'s serving mode), not the
issue-in/PR-out tool shape [`harness.md`](harness.md) describes. These rules
are inherited by every service and backed by the same mechanical gates (ruff,
pytest, CI, branch protection) as the tool harness, with the load-bearing
invariants replaced where the two shapes genuinely differ. The canonical copy
ships in `mythings/service-harness.md`; inside a service this is a **vendored
copy** kept in sync by the same drift-check mechanism as `HARNESS.md` — never
edit it in a service. To change a rule, edit the canonical in
`my-things-core`, then re-vendor every copy.

## The shape you must uphold

- The process runs continuously (or on its own schedule/trigger) instead of
  reading one GitHub issue and exiting. It is **not** issue-triggered — do not
  add an issue-polling loop to make it look like a tool; if it needs to react
  to fleet events, it exposes an API/endpoint another tool or a human calls.
- It exposes a **health/readiness surface** — a process a deploy story depends
  on must be able to say "I am up" and "I am ready to serve" independently
  (e.g. `GET /health`), so a supervisor or human can tell "starting" apart
  from "wedged" apart from "serving."
- **May not open a PR at all.** A service surfaces state or performs a single
  narrowly-scoped, already-gated write (my-server's `enqueue_issue` is the
  reference shape: fail-closed on a token, never touches another tool's PR/
  merge path); it does not inherit the tool harness's "opens a PR, never
  merges" invariant because it may never touch git the way a tool does.
- Build on the my-things-core contracts (`ledger`, `policy`, `engine`,
  `github`, `isolation`) exactly like a tool does. Do not re-implement them.
- Dependency-free runtime stays the default, but a service may take on the
  one third-party dependency its transport genuinely requires (e.g. an MCP
  SDK, a bot API client) — flagged explicitly in its own `CLAUDE.md`, not
  assumed silently the way a tool's zero-dependency runtime is.

## Config and secrets

- All configuration (tokens, ports, target org/repo) comes from the process
  environment, never a config file checked into the repo and never a CLI flag
  that would leak into shell history/process listings for a secret value.
- **Fail-closed on missing config.** A service that can't find its required
  secret must refuse to serve the capability that secret gates (same
  discipline as `my-server`'s `MYSERVER_TOKEN`), not silently degrade to an
  unauthenticated or default-open mode.
- Never persist a credential — not on disk, not in git, not in the ledger.
  Same rule as the tool harness; a service's long-running nature does not
  relax it.

## Before you touch anything / test-driven, local-first / code style / git,
## CI, and provenance / ownership & safety

Identical to [`harness.md`](harness.md) — re-read those sections there rather
than duplicating them here. The only genuine differences are the four bullets
above (process shape, health surface, PR posture, config-via-env) and the
deploy story below; everything else about how you develop, test, and commit
is the same discipline regardless of which harness a repo vendors.

## Deploy story

- A service declares how it actually runs somewhere reachable beyond a
  developer's laptop — today that's the `web_app` field in
  `tools_manifest.json` (`run` command, `port`, `hosted_url`) for an
  HTTP-serving tool; a schedule-triggered or stdio-only service (MCP) may have
  no `hosted_url` at all if it is never meant to be reachable beyond the
  invoking process. `hosted_url` stays `null` until the service is actually
  deployed somewhere — declaring one prematurely would claim a capability
  that doesn't exist yet, the same discipline `_compat`'s coherence gate
  already enforces for `core:` claims.
- CI still runs the full test suite before merge; a service adds no new CI
  shape beyond what the tool harness already specifies (Linux-only, one job,
  `concurrency: cancel-in-progress`, timeout).

## The per-service seams (fill these; everything above is fixed)

- Name `my-<x>` / package `my<x>`; one-line purpose.
- What it serves, over which transport(s).
- Its one gated write, if it has one (what triggers it, what gates it, what
  it never does) — a service without any write path says so explicitly.
- Config/secrets it reads from the environment, and what happens when one is
  missing.
- How to verify it end-to-end (start it, hit the health endpoint, exercise
  the one write path against a real or faked boundary).
