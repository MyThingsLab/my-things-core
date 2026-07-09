# MyCoder — design plan

## Purpose

The "act" tool — given one GitHub issue in a target repo, produce a code
change addressing it and open a PR (never merge). Package `mycoder`. Every
prior tool in this line reacts, reviews, tests, or reports; MyCoder is the
first that **writes and commits the feature/fix itself**. Generalizes
MyTester's exact shape (issue → deterministic pre-work → one Engine call →
PR → ledger) from "append one test function to one known file" to
"write/replace a small, explicitly-scoped set of files."

Was deferred because its Engine call ("write the diff for this issue") is
the one judgment step `NoopEngine` can't stand in for — a fixed string can't
produce working code, so it couldn't be tested end-to-end. `ClaudeCLIEngine`
(2026-07-07) removed that blocker; this doc is the real design.

**First target: MyRaytracer.** Per the user's 2026-07-08 framing ("an example
of high-difficulty codebase that can be implemented with the fleet"),
confirmed 2026-07-09 as a Monte Carlo path tracer — spheres + planes,
Lambertian materials, one pinhole camera, PPM output, deterministic given a
fixed seed. It is **not** a `My[X]` tool: no Engine call, no backlog label,
no ledger `kind` of its own — it's a plain repo whose issue backlog MyCoder
works through, the same as any other feature request would be. Its own
`README.md`/`CLAUDE.md` (once scaffolded) carry the actual scope detail;
this doc only needs to know it's the first consumer.

## The single Engine call

One subcommand, one Engine call per invocation, one issue per invocation
(mirrors MyTester: iterate by re-invoking, not by looping inside one run —
`fleet_dispatch`'s existing durable-attempt/retry machinery already covers
that layer, so MyCoder doesn't reinvent it).

### `build`

Required: "write the code for this one issue."

- **Input:** issue title + body, the **declared file scope** (see below,
  required — not inferred), the current content of each declared file
  (empty string if it doesn't exist yet, which is how new-file creation
  works), and the target repo's `CLAUDE.md`/`HARNESS.md` for style/
  invariants. `context = {"repo": str, "issue": int, "files": [str, ...]}`.
- **Output format — deliberately full-file-content, not a unified diff:**
  `data = {"files": {"path/to/file.py": "<complete new file content>", ...}}`.
  A single non-tool-use completion producing a *patch* is fragile (one
  wrong line offset and `git apply` fails outright); asking for each
  touched file's complete new content sidesteps that entirely — same
  reasoning as MyTester emitting one complete new test function rather
  than a diff against the test file. Deterministic code computes the
  actual git diff after writing, for the PR body / ledger.
- **Scope enforcement, defense in depth:** the prompt states the exact
  allowed path list; the reply is then **hard-filtered** to drop any key
  outside `context["files"]` regardless of what the model returned — same
  "never touches files outside its declared scope" invariant as MyTester's
  "never touches files outside the one test file," generalized from one
  path to a small declared set. If filtering leaves zero files, `outcome=
  failure`, no PR.
- **Against `NoopEngine`:** no generation. `build_engine("noop")` is wired
  to a fixed, safe placeholder reply scoped to whatever `context["files"]`
  turns out to be at run time — practically, a no-op edit (unchanged
  content for existing files, an empty/`pass`-only stub for new ones) so
  the mechanical write → diff → test-run → PR path can be smoke-tested
  without asserting anything about code quality. Same limitation the
  doc's "Open questions" section names directly: `NoopEngine` proves the
  plumbing, never the generation quality — identical ceiling to MyTester's
  own placeholder.

## Deterministic pre-work

1. Fetch the issue. Require an explicit, structured file-scope declaration
   in its body (e.g. a `Files:` list) — **v0 does not infer scope** via
   MySearcher or any heuristic. If absent, `outcome=skipped` ("no file
   scope declared"). This pushes the actual hard problem — decomposing
   "build a raytracer" into 20-40 issues small enough for one Engine call
   each — onto whoever files the issues (a human today; MyGroomer's
   split/label judgment and MyPlanner's sequencing are the natural
   automation path later, but neither is required to exist first).
2. Read current content of every declared file from the target repo (empty
   string for paths that don't exist).
3. Build the Engine prompt per above; call once.
4. Apply the hard scope-filter to the reply (previous section).
5. Write the surviving files into a `Workspace` (isolated worktree, never
   the live checkout).
6. Run the target repo's own test command (`pytest`, from its `pyproject.toml`
   / harness convention) inside the workspace.
   - **Pass:** commit, open PR, `outcome=success`.
   - **Fail:** no PR, `outcome=failure` — unlike MyTester's `bug_found` path
     (which surfaces a real bug in *pre-existing* code), a test failure here
     almost always means MyCoder's own new code is wrong, not a discovery
     worth a human's review time. No in-run retry; a second CLI invocation
     against the same issue is a fresh attempt (same one-Engine-call-per-run
     discipline as every other tool, and the same retry shape
     `fleet_dispatch` already implements for build attempts).
   - **Can't run at all** (e.g. new code doesn't import): `outcome=failure`,
     no PR — same "bad codegen, not a target-code bug" bucket MyTester uses.

## Ledger

- **Writes:** `kind=code`, `outcome=success|skipped|failure`, `detail`=
  "implemented issue #N" or the skip/failure reason, `data={repo, issue,
  files_touched: [str], tests_passed: bool, pr_url}`.
- **Reads:** none — one issue per run, stateless.

## Guard & Workspace

Every `git`/`gh` side effect (`checkout`, `commit`, `push`, `gh pr create`)
is wrapped as `Action(kind="bash", ...)` through `Policy.evaluate` (MyGuard)
first, same as every prior tool — but MyCoder is the first tool where the
committed *content itself* was generated, not hand-written by the invoking
session, which makes Guard's existing merge/force-push/protected-branch/
destructive-command rules the only backstop between a bad generation and a
real commit. `Workspace` isolates every write to a throwaway worktree; the
live checkout is never touched. Opens exactly **one** PR (`github.open_pr`),
**draft**, head `mycoder/<issue-number>`, base the repo's default branch,
never merges — a human (or, later, a scoped GitHub App) always merges,
same as the rest of the fleet.

**Backlog label:** none of MyCoder's *own* repo's issues — MyCoder is
invoked with `--repo <owner/repo> --issue <N>` against whatever repo it's
building (the ownership map is derived at run time, per `ARCHITECTURE.md`);
which label marks an issue "ready for MyCoder" in the *target* repo is that
repo's own convention (e.g. a human-applied `ready` label), not something
MyCoder's own repo dictates.

## CLI surface

```
mycoder build --repo <owner/repo> --issue <N> [--engine noop|claude-cli] \
              [--engine-model <model>] [--json]
```

## Test plan

- **Happy path:** issue body declares `files: ["pkg/mod.py"]`; scripted
  Engine reply returns valid content for exactly that path; mocked
  test-runner returns success; assert `outcome=success`, PR opened with the
  right head/base, `kind=code` ledger entry, `--json` prints the summary.
- **Edge (no declared scope):** issue body has no file list; assert the
  Engine is never called (spy `Engine`), `outcome=skipped`.
- **Scope-violation guard:** scripted Engine reply includes a file outside
  `context["files"]`; assert it's dropped before writing; a reply with
  *only* out-of-scope files yields `outcome=failure`, no PR, no commit.
- **Failing generated code:** mocked test-runner returns failure; assert no
  commit, no PR, `outcome=failure`.
- **`NoopEngine` smoke test:** `--engine noop` against a real declared file;
  assert the placeholder write is a genuine no-op (existing tests still
  pass), `outcome=success`, PR still opens — proves the wiring, not the
  generation quality (documented limitation, shared with MyTester).
- Mock the Engine and the target repo's `git`/`gh`/test-runner boundaries;
  the scope-filter and diff-computation logic run against real fixtures,
  never mocked. A real-`ClaudeCLIEngine` smoke test against a toy repo is
  `@pytest.mark.slow`, run manually before shipping, not in the default CI
  suite (matches the harness's "mock only at system boundaries" rule while
  keeping a real end-to-end check available).

## Dependencies & build order

Depends on core `ledger`, `policy`, `engine`, `github`, `isolation` — all
five contracts, the first tool to need every one. No new `github.GitHub`
method beyond what already exists (`list_issues`, `open_pr`, `pr_status`
cover it). Built out of the numbered recommended-build-order list (see
`README.md`) because the user asked for it directly as the fleet's
highest-signal readiness test, not because it's next by dependency.

**Open questions:**

- **Issue decomposition is the real bottleneck, not the Engine call.**
  MyCoder can only be as good as the issues it's handed. "Build a Monte
  Carlo path tracer" is not one issue; producing ~20-40 issues each small
  enough for one full-file-content Engine reply is itself unautomated
  today (MyGroomer/MyPlanner would help once built, but aren't
  prerequisites for MyCoder's own build). Expect the first several
  MyRaytracer issues to be hand-written and hand-scoped as a result.
- **Full-file-content vs. unified diff, confirmed for v0, revisit if
  files grow large.** Full-content is simpler and more reliable from a
  single non-tool-use completion, but resending an entire file's content
  on every touch wastes tokens on large files. Not a problem at
  MyRaytracer's likely file sizes; would need revisiting for a target
  repo with large existing files.
- **No cross-issue memory.** Each `build` call sees only its own declared
  files, not the rest of the target repo — an issue that needs to know
  about a sibling module's API (e.g. "add a `Sphere` that satisfies the
  `Hittable` protocol defined elsewhere") must say so explicitly in its
  body/declared-files list; MyCoder does not go looking.
- **This is the fleet's biggest trust step.** Every invariant above
  (Workspace isolation, hard scope-filter, Guard on every side effect,
  draft-never-merge, test-run-before-commit) exists because this is the
  first tool whose committed content wasn't written by the invoking
  session — confirm this list is exhaustive before implementation starts,
  not after a bad generation gets committed.
