from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

# The semantic-retrieval seam, sibling of mythings.corpus. corpus scores by
# lexical TF-IDF; measured against the real study corpus that breaks in four
# ways nothing lexical can fix (docs/adr/0003): math notation the tokenizer
# drops, paraphrase with no shared words, terms that live only in notation, and
# a cross-language query (Italian materials over English briefs). An Embedder
# turns text into a vector where nearness is *meaning*, not shared tokens, so
# corpus.shortlist can fuse the two signals.
#
# Same shape as engine.Engine: a Protocol with a dependency-free deterministic
# default (HashingEmbedder, the NoopEngine analog — makes every consumer
# testable with zero network) and a real backend that adds no Python dependency
# (ApiEmbedder shells out over stdlib urllib, mirroring ClaudeCLIEngine's
# shell-out to the `claude` CLI). Inert by default; core stays dependencies=[].

Vector = tuple[float, ...]

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[Vector]: ...


def cosine(a: Vector, b: Vector) -> float:
    # Guards the zero vector (an empty text under HashingEmbedder) so a caller
    # never divides by zero — an empty text is simply "near nothing", 0.0.
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    num = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


def _normalize(values: list[float]) -> Vector:
    norm = math.sqrt(sum(v * v for v in values))
    if not norm:
        return tuple(values)
    return tuple(v / norm for v in values)


class HashingEmbedder:
    # Deterministic, stdlib-only feature hashing: each token lands in a bucket
    # by its hash, with a hashed sign to cancel some collisions, and the vector
    # is L2-normalized. This is the seam's NoopEngine — it makes every consumer
    # runnable and testable with no network and no tokens, and it degrades an
    # ApiEmbedder failure honestly. It is NOT semantic: hashing shares no bucket
    # between "eigenvalue" and "characteristic root", so it does not fix the
    # paraphrase/notation/cross-language gaps — only a real backend does. Its
    # job is to keep the pipeline whole when no backend is configured.
    def __init__(self, *, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> Vector:
        acc = [0.0] * self._dim
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            acc[bucket] += sign
        return _normalize(acc)


# A Poster takes (url, body, headers) and returns the raw response bytes. The
# default hits the network over stdlib urllib; tests inject a fake so the HTTP
# boundary is the only thing mocked, exactly like engine.Runner / github.Runner.
Poster = Callable[[str, bytes, dict[str, str]], bytes]


def _urllib_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - configured URL
        return response.read()


class ApiEmbedder:
    # The real semantic backend, over an OpenAI-compatible /v1/embeddings
    # endpoint (the de-facto shape OpenAI, llama.cpp, Ollama and LM Studio all
    # expose) — POST {"model", "input": [...]} -> {"data": [{"embedding": [...]}]}.
    # Adds no Python dependency: stdlib urllib, the embedding analog of
    # ClaudeCLIEngine shelling out to a CLI. URL/model/key come from the
    # environment so wiring one in is config, not code.
    #
    # Never raises. Any transport, HTTP, or parse failure — including no URL
    # configured at all — degrades to the `fallback` embedder (HashingEmbedder
    # by default), so retrieval keeps working, just less semantically, the same
    # honest degrade as ClaudeCLIEngine returning an empty EngineResult. A
    # caller wanting to *know* it degraded checks whether a URL was configured.
    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        poster: Poster = _urllib_post,
        fallback: Embedder | None = None,
        batch: int = 64,
    ) -> None:
        self._url = url if url is not None else os.environ.get("MYTHINGS_EMBED_URL", "")
        self._model = model if model is not None else os.environ.get("MYTHINGS_EMBED_MODEL", "")
        self._key = api_key if api_key is not None else os.environ.get("MYTHINGS_EMBED_KEY", "")
        self._post = poster
        self._fallback = fallback or HashingEmbedder()
        self._batch = max(1, batch)

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        if not self._url:
            return self._fallback.embed(texts)
        items = list(texts)
        try:
            out: list[Vector] = []
            for start in range(0, len(items), self._batch):
                out.extend(self._embed_batch(items[start : start + self._batch]))
            # A short/empty reply must not silently drop rows — a caller zips
            # vectors back to its chunks by position, so a length mismatch would
            # misalign every citation. Treat it as a failure and degrade whole.
            if len(out) != len(items):
                return self._fallback.embed(items)
            return out
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
            return self._fallback.embed(items)

    def _embed_batch(self, batch: Sequence[str]) -> list[Vector]:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        body = json.dumps({"model": self._model, "input": list(batch)}).encode("utf-8")
        raw = self._post(self._url, body, headers)
        obj = json.loads(raw)
        rows = obj["data"]
        # Preserve request order regardless of whether the server echoes an
        # `index` field: sort by it when present, else trust positional order.
        if all(isinstance(r, dict) and "index" in r for r in rows):
            rows = sorted(rows, key=lambda r: r["index"])
        return [_normalize([float(v) for v in row["embedding"]]) for row in rows]


class CachingEmbedder:
    # Wraps any Embedder in a content-addressed disk cache. An embedding is a
    # pure function of (text, model/tag), and re-clustering a shelf re-embeds
    # the identical chunks every run, so this turns the second and later runs
    # free — same reasoning as CachingEngine and corpus.cached_extractor, and
    # opt-in and inert the same way: constructed explicitly, touches no disk
    # until embed() is called, stdlib only.
    #
    # `tag` namespaces the cache (pass the model name) so switching models does
    # not serve one model's vectors for another's text.
    def __init__(self, delegate: Embedder, cache_dir: str | Path, *, tag: str = "") -> None:
        self._delegate = delegate
        self._dir = Path(cache_dir)
        self._tag = tag

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        items = list(texts)
        results: list[Vector | None] = [None] * len(items)
        misses: list[int] = []
        for i, text in enumerate(items):
            cached = self._read(text)
            if cached is None:
                misses.append(i)
            else:
                results[i] = cached
        # One delegate call for every miss, order preserved — never one call
        # per text, so a real backend still batches.
        if misses:
            fresh = self._delegate.embed([items[i] for i in misses])
            for i, vector in zip(misses, fresh, strict=True):
                results[i] = vector
                self._write(items[i], vector)
        return [v if v is not None else () for v in results]

    def _entry(self, text: str) -> Path:
        key = hashlib.sha256(f"{self._tag}\0{text}".encode()).hexdigest()
        return self._dir / (key + ".json")

    def _read(self, text: str) -> Vector | None:
        try:
            return tuple(json.loads(self._entry(text).read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write(self, text: str, vector: Vector) -> None:
        # Never cache an empty vector: a degraded/short backend reply yields ()
        # for a row, and remembering that would poison the text forever.
        if not vector:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        entry = self._entry(text)
        tmp = entry.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(list(vector)), encoding="utf-8")
        tmp.replace(entry)
