# MyKnowledger — design plan

**Redesigned.** Earlier drafts of this doc described a project-history Q&A
tool; that tool is renamed [MyWiki](my-wiki.md) so this name is free for
its intended scope: *external* domain knowledge.

## Purpose

Answers technical/domain questions grounded in an external knowledge
corpus — papers, books, articles, web sources — ingested via the
`graphify` skill, entirely separate from MyWiki's project-history corpus
and from MyGrapher's code-repo corpus. Package `myknowledger`, backlog
label `my-knowledger`.

## The single Engine call

Two subcommands, each a separate invocation making exactly one Engine call
(same per-run discipline as MyResearcher's `brief`/`plan` split).

### `ask` (default)

Required: "answer this question using only the given excerpts from the
external knowledge graph."

- **Input:** the question (issue title + body) plus a deterministically
  retrieved shortlist of nodes/passages from an existing external
  `graphify-out/` corpus, via `graphify query "<question>"` — this is
  graphify's own retrieval traversal (BFS/DFS), not extraction, so it's
  LLM-free. `context = {"question_issue": N, "candidate_count": k}`.
- **Output:** `data = {"answer": str, "cited": [source_id, ...]}` —
  citations point at specific ingested sources (paper title/section, URL,
  book + page, whatever metadata graphify's nodes carry). Same discipline
  as MyWiki: the model may only cite from the given excerpts.
- Against `NoopEngine`: no synthesis — prints the retrieved passages
  verbatim with their source citations, same honest degrade as MyWiki.

### `verify` (absorbs the "my-fact-check" idea, 2026-07-08)

A separately proposed "my-fact-check" turned out to be the identical
"retrieve, then the model may only cite the given excerpts" shape as
`ask`, just phrased as a claim to check rather than a question to answer.
Added as a second subcommand on this tool instead of a sixth standalone
"retrieve then cite" repo.

Required: "using only the given excerpts, judge whether this claim holds."

- **Input:** the claim (issue title + body) plus the same
  `graphify query "<claim>"` shortlist as `ask`. `context =
  {"claim_issue": N, "candidate_count": k}`.
- **Output:** `data = {"verdict": "supported"|"contradicted"|"unclear",
  "explanation": str, "cited": [source_id, ...]}` — same cite-only
  discipline as `ask`; `"unclear"` is the honest answer when the corpus
  neither supports nor contradicts the claim, not a forced binary.
- Against `NoopEngine`: `verdict="unclear"`, explanation = the retrieved
  passages verbatim — same honest degrade as `ask`.

## Deterministic pre-work

Both subcommands share the same steps, keyed on the question or claim text:

1. Read the issue (label `my-knowledger`).
2. Confirm an external-knowledge `graphify-out/` corpus already exists —
   see the invariant below; MyKnowledger never builds one.
3. Run `graphify query "<question-or-claim>"` (or `--dfs` to trace one
   specific thread) against that corpus.
4. Cap the retrieved excerpt set with graphify's own `--budget` flag — same
   size-cap discipline as every other retrieval tool in this batch
   (MySearcher's candidate cap, MyReviewer's diff cap, MyWiki's shortlist
   cap).
5. If retrieval returns nothing, skip the Engine call and post "no
   relevant source found in the knowledge corpus" (`ask`) or "no source
   to confirm or contradict this claim" (`verify`) — same deterministic
   short-circuit as MyWiki's no-match case.

## Ledger

- **`ask` writes:** `kind=knowledge`, `outcome=success|skipped`,
  `detail`=the question (truncated), `data={question, cited_sources,
  comment_url}`.
- **`verify` writes:** `kind=fact_check`, `outcome=success|skipped`,
  `detail`=the claim (truncated), `data={claim, verdict, cited_sources,
  comment_url}` — a distinct `kind` so verify entries never collide with
  `ask` entries.
- **Reads:** nothing beyond the external graph — no dedupe needed; the same
  question or claim can be asked more than once without collision (unlike
  MyReviewer/MyDescriber, which dedupe against an unchanged diff).

## Guard & Workspace

- No `Workspace`, no PR — comment-only side effect through `Policy`,
  `ALLOW` by default, same as MyWiki/MyReporter/MySearcher's comment paths.
- **Invariant: MyKnowledger never ingests new sources itself** — mirrors
  MyGrapher's "never bootstraps" invariant exactly. Growing the corpus
  (`graphify add <url>`, or `graphify <path> --mode deep` over a folder of
  downloaded papers) is a human/interactive-session action, done out of
  band, because graphify's ingestion path calls an LLM for entity
  extraction. Importing that into MyKnowledger's own CI-invoked run would
  smuggle a second hidden Engine call into a tool whose harness contract
  says exactly one — the same problem already resolved for MyGrapher, and
  resolved here the same way.

## CLI surface

```
myknowledger ask    --issue <number> [--corpus-path <path>]
myknowledger verify --issue <number> [--corpus-path <path>]
```

## Test plan

- **`ask` happy path:** a fixture external graph (a couple of
  ingested-paper nodes) and a question matching one of them; scripted
  `Engine` reply citing it; assert the comment includes the citation and
  `kind=knowledge`/`outcome=success` is written.
- **`ask` edge case (no match):** retrieval returns nothing; assert the
  Engine is never called (spy `Engine`) and `outcome=skipped`.
- **`verify` happy path:** the same fixture graph with a claim it
  contradicts; scripted `Engine` reply with `verdict="contradicted"`;
  assert the comment renders the verdict + citation and
  `kind=fact_check`/`outcome=success` is written.
- **`verify` edge case (no match):** assert the Engine is never called and
  `outcome=skipped`, mirroring `ask`'s edge case.
- Mock `github.Runner` and the `graphify`/`graphifyy` CLI subprocess
  boundary (same fake-runner style as MyGrapher's tests); never mock the
  retrieval-then-cite shape itself.

## Dependencies & build order

Depends on core `ledger`, `github`, `policy`. Depends on the
`graphify`/`graphifyy` CLI (external dependency, same flag already raised
for MyGrapher and MyTelegramBot) and a pre-bootstrapped external-knowledge
corpus (built out of band, by a human). Independent of MyWiki — same
"shortlist, then one Engine call to cite an answer" shape, different
corpus — but shares enough structure with it, MySearcher, MyAdvisor, and
MyDescriber that this is now the **fifth** tool doing "retrieve then cite,"
which is a real signal for a shared core helper (see the cross-cutting
note in [README.md](README.md)). Build alongside or after MyGrapher — both
share the "requires a pre-bootstrapped `graphify-out/`, never bootstraps it
itself" invariant and the same mocked-CLI test style, so building them
close together avoids re-deriving that pattern twice.

**Open questions:**
- **Where does the external corpus live?** It isn't code, and isn't tied
  to any single tool repo — likely a dedicated location at the workspace
  level (e.g. `MyThingsLab/knowledge/` with its own `graphify-out/`),
  separate from any git repo the harness manages, since it's shared
  reference material rather than something that ships with a tool. Not
  decided.
- Should source PDFs/books themselves be checked into that location for
  provenance/reproducibility, or just the ingested graph (smaller, but the
  source of truth then lives externally — a reading list, a Zotero
  library)? Flagged, not decided.
- **Five tools now independently reuse a "shortlist from a corpus, then one
  Engine call to cite an answer" shape** (MyWiki, MySearcher's ranking,
  MyAdvisor, MyDescriber, MyKnowledger). Strong enough signal to consider a
  shared retrieval-and-cite helper in `my-things-core` — though putting
  RAG-specific shape into a dependency-free SDK deserves its own
  discussion before committing, not decided by accretion here.
