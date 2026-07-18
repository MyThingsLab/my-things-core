from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from mythings.embed import Embedder, cosine

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

# An Extractor turns a file into plain text. The default shells out to
# `pdftotext` (poppler) for PDFs, mirroring github.Runner's shell-out to `gh`:
# core keeps `dependencies = []` because poppler is a system binary, not a
# Python package, and a caller can inject a pure extractor in tests.
Extractor = Callable[[Path], str]


@dataclass(frozen=True)
class Document:
    id: str
    path: str
    title: str
    text: str
    # True when `text` extracted suspiciously little relative to the source
    # PDF's page count -- almost always an image-only scan pdftotext could not
    # read, not a genuinely short document. ingest() sets this; it never drops
    # or skips the document, so a sparse Document still joins the corpus, but a
    # consumer can now tell "this contributed nothing" apart from "this is
    # legitimately short" instead of the silent empty-but-valid entry before.
    sparse: bool = False


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    ordinal: int
    text: str
    # Character offsets into the parent Document.text, so a Citation can be
    # resolved back to the exact span a claim came from.
    start: int
    end: int


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    ordinal: int
    start: int
    end: int

    def marker(self) -> str:
        return f"[{self.doc_id}:{self.ordinal}]"


def tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text) if tok}


def _pdftotext(path: Path) -> str:
    proc = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed on {path}: {proc.stderr.strip()}")
    return proc.stdout


def extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _pdftotext(path)
    return path.read_text(encoding="utf-8")


def cached_extractor(cache_dir: Path, *, extractor: Extractor = extract) -> Extractor:
    # Extracting a shelf of PDFs costs tens of seconds and the text never changes
    # while the file doesn't, so an interactive caller re-pays that on every
    # query. Opt-in by construction: this returns an Extractor, so core still
    # touches no disk unless a caller asks for a cache and names the directory.
    # Keyed on (size, mtime_ns) as well as path, so editing a file invalidates it.
    def _extract(path: Path) -> str:
        stat = path.stat()
        key = f"{path.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}"
        entry = cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".txt")
        try:
            return entry.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
        text = extractor(path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write must not leave a truncated entry
        # that later reads would trust as a complete extraction.
        tmp = entry.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(entry)
        return text

    return _extract


def _slug(stem: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "doc"


# A PageCounter reports a PDF's page count (or None if it can't be determined),
# mirroring Extractor's shell-out-to-a-system-binary shape -- same
# `dependencies = []` reasoning as pdftotext.
PageCounter = Callable[[Path], int | None]

_PDFINFO_PAGES_RE = re.compile(r"^Pages:\s*(\d+)", re.MULTILINE)


def _pdfinfo_pages(path: Path) -> int | None:
    proc = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    match = _PDFINFO_PAGES_RE.search(proc.stdout)
    return int(match.group(1)) if match else None


# A PDF this sparse relative to its page count is almost always an image-only
# scan pdftotext could not read -- real prose runs to hundreds of characters
# per page at minimum. Deliberately conservative (option 1 from #96: warn/flag,
# never skip) so a legitimately terse PDF is never misflagged, let alone
# dropped from the corpus.
SPARSE_CHARS_PER_PAGE = 10.0


def ingest(
    paths: Iterable[Path],
    *,
    extractor: Extractor = extract,
    page_counter: PageCounter = _pdfinfo_pages,
) -> list[Document]:
    documents: list[Document] = []
    seen: dict[str, int] = {}
    for path in paths:
        base = _slug(path.stem)
        # Two files may slug identically (a.pdf, A.PDF). Suffix deterministically
        # rather than silently dropping one -- doc_id is a citation key.
        count = seen.get(base, 0)
        seen[base] = count + 1
        doc_id = base if count == 0 else f"{base}-{count + 1}"
        text = extractor(path)
        sparse = False
        if path.suffix.lower() == ".pdf":
            pages = page_counter(path)
            if pages:
                sparse = (len(text) / pages) < SPARSE_CHARS_PER_PAGE
        documents.append(
            Document(id=doc_id, path=str(path), title=path.stem, text=text, sparse=sparse)
        )
    return documents


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for part in text.split("\n\n"):
        if part.strip():
            lead = len(part) - len(part.lstrip())
            trail = len(part) - len(part.rstrip())
            spans.append((pos + lead, pos + len(part) - trail))
        pos += len(part) + 2
    return spans


def chunk(doc: Document, *, target_chars: int = 1200) -> list[Chunk]:
    # No overlap between chunks: token-overlap scoring gains nothing from it,
    # and overlapping spans would let one claim cite two chunks of the same
    # sentence. Chunks tile the document's prose exactly once.
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")

    chunks: list[Chunk] = []

    def emit(start: int, end: int) -> None:
        chunks.append(
            Chunk(
                doc_id=doc.id,
                ordinal=len(chunks),
                text=doc.text[start:end],
                start=start,
                end=end,
            )
        )

    cur_start: int | None = None
    cur_end = 0
    for start, end in _paragraph_spans(doc.text):
        if end - start > target_chars:
            if cur_start is not None:
                emit(cur_start, cur_end)
                cur_start = None
            # A single paragraph wider than the target (a table, a long proof):
            # hard-split it rather than emit one oversized chunk.
            for cut in range(start, end, target_chars):
                emit(cut, min(cut + target_chars, end))
            continue
        if cur_start is None:
            cur_start, cur_end = start, end
        elif end - cur_start <= target_chars:
            cur_end = end
        else:
            emit(cur_start, cur_end)
            cur_start, cur_end = start, end
    if cur_start is not None:
        emit(cur_start, cur_end)
    return chunks


def _term_freq(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tok in _TOKEN_RE.findall(text):
        key = tok.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _idf(freqs: list[dict[str, int]]) -> dict[str, float]:
    # Rare tokens discriminate; common ones do not. Without this, a query token
    # like "algorithm" -- present in nearly every chunk of a textbook -- counts
    # as much as the one rare token that actually identifies the passage.
    n = len(freqs)
    doc_freq: dict[str, int] = {}
    for tf in freqs:
        for token in tf:
            doc_freq[token] = doc_freq.get(token, 0) + 1
    # Smoothed: log(1 + n/(1+df)) is strictly positive, so a token occurring in
    # every chunk still scores a real (small) match rather than zero. The plain
    # log(n/(1+df)) goes negative there, which would push an all-chunks-match
    # query onto the "nothing scored" degrade path -- a silent behaviour change.
    return {token: math.log(1 + n / (1 + df)) for token, df in doc_freq.items()}


_PAGE_NUMBER_LINE_RE = re.compile(r"\d+\s*$")
_DOT_LEADER_RE = re.compile(r"(?:\.\s?){3,}")


def _is_boiler_line(line: str) -> bool:
    # A table-of-contents/index/bibliography line overwhelmingly ends in a bare
    # page number or a run of dot leaders -- prose almost never does (a
    # sentence ends in punctuation; a wrapped line still trails a word).
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_PAGE_NUMBER_LINE_RE.search(stripped)) or bool(_DOT_LEADER_RE.search(stripped))


def _boiler_ratio(text: str) -> float:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    return sum(1 for ln in lines if _is_boiler_line(ln)) / len(lines)


def shortlist(
    chunks: Iterable[Chunk],
    query: str,
    *,
    top: int = 8,
    embedder: Embedder | None = None,
) -> list[Chunk]:
    candidates = list(chunks)
    query_tokens = tokenize(query)
    freqs = [_term_freq(c.text) for c in candidates]
    weights = _idf(freqs)
    # TF-IDF, not bare overlap. Set intersection alone cannot separate the
    # section that explains a term (which repeats it) from the abstract that
    # merely name-drops it once, nor from a bibliography entry that happens to
    # carry the words in a cited paper's title. The tf term is log-damped so a
    # chunk cannot win on sheer repetition alone.
    #
    # Down-weight (not exclude) by boiler_ratio: a reference-list entry whose
    # cited title repeats the query words still ranks high on TF-IDF alone
    # (#90) -- it's navigation text, not prose, so it's scaled toward zero
    # rather than dropped, since an occasional false positive (a genuine
    # section header ending in a number) should still be able to win on the
    # underlying TF-IDF score rather than being silently discarded.
    scored = [
        (
            sum((1 + math.log(tf[t])) * weights.get(t, 0.0) for t in query_tokens & tf.keys())
            * (1 - _boiler_ratio(c.text)),
            c,
        )
        for tf, c in zip(freqs, candidates, strict=True)
    ]
    if embedder is not None:
        # Hybrid: fuse the lexical ranking with a semantic one so a query that
        # shares no words with the passage (paraphrase, notation, another
        # language — the failure modes measured in docs/adr/0003) can still
        # surface it. Opt-in by construction: with no embedder the path below is
        # byte-for-byte the original lexical behaviour, so wiring it in never
        # changes a caller that did not ask for it.
        return _fuse(candidates, query, scored, embedder, top)
    if query_tokens and any(score > 0 for score, _ in scored):
        ranked = sorted(scored, key=lambda item: (-item[0], item[1].doc_id, item[1].ordinal))
        return [c for _, c in ranked[:top]]
    # Nothing scored (or the query carried no usable tokens): fall back to the
    # opening chunks in document order. A weak ranking is still usable, per
    # my-searcher's shortlist(); its mtime fallback is meaningless for chunks.
    return candidates[:top]


def _fuse(
    candidates: list[Chunk],
    query: str,
    scored: list[tuple[float, Chunk]],
    embedder: Embedder,
    top: int,
) -> list[Chunk]:
    if not candidates:
        return []
    order = list(range(len(candidates)))

    def tie(i: int) -> tuple[str, int]:
        return (candidates[i].doc_id, candidates[i].ordinal)

    # Rank every candidate by each signal independently (deterministic
    # tie-break), including zero-lexical-score chunks — a chunk strong in either
    # signal should surface, which is the whole point of fusing them.
    lex_order = sorted(order, key=lambda i: (-scored[i][0], *tie(i)))
    lex_rank = {i: r for r, i in enumerate(lex_order)}

    vectors = embedder.embed([c.text for c in candidates])
    query_vector = embedder.embed([query])[0]
    sims = [cosine(query_vector, v) for v in vectors]
    vec_order = sorted(order, key=lambda i: (-sims[i], *tie(i)))
    vec_rank = {i: r for r, i in enumerate(vec_order)}

    # Reciprocal-rank fusion (the standard k=60). Combining rank positions, not
    # the raw TF-IDF and cosine scores, sidesteps the fact that the two live on
    # different, incomparable scales — no normalisation constant to tune.
    k = 60
    fused = sorted(
        order,
        key=lambda i: (-(1.0 / (k + lex_rank[i]) + 1.0 / (k + vec_rank[i])), *tie(i)),
    )
    return [candidates[i] for i in fused[:top]]


def cite(chunks: Iterable[Chunk], documents: Iterable[Document]) -> list[Citation]:
    titles = {doc.id: doc.title for doc in documents}
    citations: list[Citation] = []
    for c in chunks:
        if c.doc_id not in titles:
            raise ValueError(f"chunk cites unknown document {c.doc_id!r}")
        citations.append(
            Citation(
                doc_id=c.doc_id,
                title=titles[c.doc_id],
                ordinal=c.ordinal,
                start=c.start,
                end=c.end,
            )
        )
    return citations
