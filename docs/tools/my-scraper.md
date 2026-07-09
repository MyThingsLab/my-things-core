# MyScraper — design plan

## Purpose

Given a URL and a question, fetch the page **deterministically** and run **one
Engine call** to extract structured data answering the question — "give it a
URL + a question, get structured data back." Package `myscraper`, backlog
label `my-scraper`.

Distinct from its neighbours:

- **MyResearcher** *discovers* sources (search + arXiv) across a topic and
  synthesizes a cited brief. MyScraper takes a **single already-known URL**
  and extracts — no discovery, no synthesis across sources.
- **MyKnowledger** answers from a **pre-built** corpus. MyScraper never builds
  or reads a corpus — each run is one URL, stateless.
- **MySearcher** ranks files **within a repo**. MyScraper fetches **external**
  web content — the two never overlap in input space.

Explicitly out of scope for v0: crawling, pagination, following links,
multi-page sites. One URL in, one structured record out. (If site-wide
crawling is wanted later, that's a distinct tool/mode — robots.txt/rate-limit/
politeness concerns make it a bigger contract than this one.)

## The single Engine call

One subcommand, one Engine call per run.

### `extract`

Required: "given this page's cleaned text and a question, extract structured
data answering it."

- **Input:** the fetched page's cleaned text (HTML stripped to visible text,
  size-capped — see pre-work), the question/schema, and
  `context = {"url": str, "fetched_chars": int, "truncated": bool}`.
- **Output:** `data = {"answer": str, "fields": {...}, "confidence":
  "high"|"low", "quote": str}` — `fields` is free-form JSON matching whatever
  the caller's question implies (e.g. `--question "price and availability"` →
  `{"price": "...", "availability": "..."}`); `quote` must be a **verbatim
  substring of the fetched text** (same no-invention discipline as
  MySearcher's permutation rule / MyKnowledger's cite-only rule) — a quote
  that doesn't appear in the source text is dropped and `confidence` forced to
  `"low"`.
- Against `NoopEngine`: no extraction — emits the raw cleaned text
  (size-capped) verbatim as `fields = {"raw_text": str}`, same honest degrade
  as MyResearcher/MyKnowledger.

## Deterministic pre-work

1. Fetch the URL over **stdlib HTTP** (`urllib.request`, no SDK, per the
   harness's dependency-free rule) with a short timeout and a
   `MyScraper/<version>` user-agent. Single redirect chain followed
   (stdlib default); no retries beyond that.
2. Check `robots.txt` for the URL's origin first (stdlib `urllib.robotparser`)
   — if disallowed for our user-agent, **skip the fetch and the Engine call**,
   outcome `skipped`. Politeness gate, not a crawler-scale concern, since it's
   one page per run.
3. Strip HTML to visible text: stdlib `html.parser.HTMLParser` subclass
   dropping `<script>`/`<style>`/`<nav>`/`<footer>` content and collapsing
   whitespace — no new parsing dependency.
4. Size-cap the cleaned text (default 20,000 chars) before it reaches the
   Engine prompt — the same size-cap discipline as every retrieval tool in the
   line; `context.truncated=true` if cut.
5. If the fetch fails (non-2xx, timeout, connection error, robots-disallowed,
   or the stripped text is empty), **skip the Engine call** and record the
   failure reason — deterministic short-circuit, same as MyResearcher's
   "no sources found."

## Ledger

- **Writes:** `kind=scrape`, `outcome=success|skipped`, `detail`="extracted
  from `<url>`" or the skip reason, `data={url, question, fields, truncated,
  comment_url}`.
- **Reads:** none — each run is stateless and independent (no cross-run
  corpus, unlike MyKnowledger).

## Guard & Workspace

**No `Workspace`, no PR.** This is a read-only utility — like MySearcher, not
like MyResearcher/MyTester. Output goes to stdout (`--json`) and/or, if
`--issue` is given, an issue comment via `Action(kind="bash", ...)` routed
through `Policy.evaluate()` (`ALLOW` by default). Nothing is ever committed to
a repo.

Boundaries:

- All network is deterministic (no model call), stdlib-only, so it stays
  outside the one-Engine-call contract — same posture as MyResearcher's HTTP
  layer. In the default suite the HTTP boundary is **mocked**; any real-network
  test is `@pytest.mark.slow`.
- **Never crawls.** One URL per invocation, no link-following — the fence that
  keeps this tool's contract small; a future MyCrawler (if ever wanted) is a
  separate repo, not a flag here.
- robots.txt is honored, not bypassed — no user-agent spoofing to get around a
  disallow.

## CLI surface

```
myscraper extract --url <url> --question "<question>" [--issue N] [--comment] \
                   [--max-chars 20000] [--json]
```

## Test plan

- **Happy path:** a fixture HTML page (mocked HTTP), a scripted `Engine` reply
  with `fields`/`quote`; assert the quote is verified against the cleaned
  text, `outcome=success`, `kind=scrape` is written, `--json` prints the
  record.
- **Edge (fetch failure):** mocked HTTP raises/returns 404; assert the Engine
  is never called (spy `Engine`), `outcome=skipped`, failure reason recorded.
- **Edge (robots disallow):** mocked robots.txt disallows the path; assert
  fetch never happens, Engine never called, `outcome=skipped`.
- **NoopEngine degrade:** assert raw cleaned text is returned as
  `fields.raw_text` and the run still succeeds.
- **Quote-invention guard:** scripted `Engine` reply with a `quote` not present
  in the source text; assert it's dropped and `confidence` is forced to
  `"low"`.
- Mock the HTTP boundary; HTML-stripping and quote-verification logic run
  against real fixtures, never mocked. One live-network smoke test is
  `@pytest.mark.slow`.

## Dependencies & build order

Depends on core `ledger` and `policy` only — no `github`/`isolation` needed
since there's no PR path (comment posting reuses `github.Runner` the same way
MySearcher's `--comment` does, but that's the only github touchpoint).
Stdlib-only HTTP/HTML (`urllib.request`, `urllib.robotparser`,
`html.parser`) — no new runtime SDK, per the harness. Standalone; no
dependency on any other tool. A natural feeder for a human to hand extracted
data into MyKnowledger's corpus out of band, same "producer, never ingests
itself" posture MyResearcher holds.

**Open questions:**

- **JS-rendered pages.** v0 is static-HTML-only (stdlib fetch, no browser).
  Sites that render content client-side will yield thin/empty text and fall
  into the "empty stripped text" skip path. A headless-browser fetch mode
  would pull in a real dependency (Playwright) — explicitly deferred, not
  decided here.
- **`fields` shape validation.** The Engine's `fields` object is free-form
  JSON today (whatever the question implies). A `--schema <json-schema-file>`
  flag to validate/constrain it is a natural v1 addition, not required for v0.
- **Confirm `kind=scrape`** doesn't collide with an existing ledger `kind`
  before implementation.
