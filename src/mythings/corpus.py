from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

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


def _slug(stem: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "doc"


def ingest(paths: Iterable[Path], *, extractor: Extractor = extract) -> list[Document]:
    documents: list[Document] = []
    seen: dict[str, int] = {}
    for path in paths:
        base = _slug(path.stem)
        # Two files may slug identically (a.pdf, A.PDF). Suffix deterministically
        # rather than silently dropping one -- doc_id is a citation key.
        count = seen.get(base, 0)
        seen[base] = count + 1
        doc_id = base if count == 0 else f"{base}-{count + 1}"
        documents.append(Document(id=doc_id, path=str(path), title=path.stem, text=extractor(path)))
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


def shortlist(chunks: Iterable[Chunk], query: str, *, top: int = 8) -> list[Chunk]:
    candidates = list(chunks)
    query_tokens = tokenize(query)
    scored = [(len(query_tokens & tokenize(c.text)), c) for c in candidates]
    if query_tokens and any(score > 0 for score, _ in scored):
        ranked = sorted(scored, key=lambda item: (-item[0], item[1].doc_id, item[1].ordinal))
        return [c for _, c in ranked[:top]]
    # Nothing scored (or the query carried no usable tokens): fall back to the
    # opening chunks in document order. A weak ranking is still usable, per
    # my-searcher's shortlist(); its mtime fallback is meaningless for chunks.
    return candidates[:top]


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
