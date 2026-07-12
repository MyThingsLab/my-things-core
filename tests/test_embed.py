from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from mythings.embed import (
    ApiEmbedder,
    CachingEmbedder,
    HashingEmbedder,
    cosine,
)

# --- cosine ------------------------------------------------------------------


def test_cosine_identical_is_one_and_orthogonal_is_zero() -> None:
    assert cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_cosine_zero_vector_is_zero_not_error() -> None:
    assert cosine((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_cosine_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        cosine((1.0,), (1.0, 2.0))


# --- HashingEmbedder ---------------------------------------------------------


def test_hashing_is_deterministic_and_normalized() -> None:
    e = HashingEmbedder(dim=64)
    a = e.embed(["gradient descent minimises the loss"])
    b = e.embed(["gradient descent minimises the loss"])
    assert a == b  # deterministic — the property clustering relies on
    (vec,) = a
    assert len(vec) == 64
    assert sum(v * v for v in vec) == pytest.approx(1.0)  # unit length


def test_hashing_similar_text_scores_higher_than_unrelated() -> None:
    e = HashingEmbedder(dim=512)
    (base,) = e.embed(["k means clustering of the data points"])
    (near,) = e.embed(["clustering the data points with k means"])
    (far,) = e.embed(["hamiltonian mechanics and phase space"])
    assert cosine(base, near) > cosine(base, far)


def test_hashing_empty_text_is_zero_vector() -> None:
    (vec,) = HashingEmbedder(dim=8).embed([""])
    assert vec == (0.0,) * 8


def test_hashing_rejects_nonpositive_dim() -> None:
    with pytest.raises(ValueError):
        HashingEmbedder(dim=0)


# --- ApiEmbedder -------------------------------------------------------------


def _fake_poster(payloads: list[list[float]]):
    # Returns an OpenAI-shaped response echoing one embedding per input row.
    def post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        req = json.loads(body)
        rows = [
            {"index": i, "embedding": payloads[i % len(payloads)]}
            for i, _ in enumerate(req["input"])
        ]
        return json.dumps({"data": rows}).encode()

    return post


def test_api_embedder_parses_and_normalizes() -> None:
    e = ApiEmbedder(url="http://x/v1/embeddings", model="m", poster=_fake_poster([[3.0, 4.0]]))
    (vec,) = e.embed(["hello"])
    assert vec == pytest.approx((0.6, 0.8))  # 3-4-5 triangle, normalized


def test_api_embedder_without_url_falls_back_to_hashing() -> None:
    fallback = HashingEmbedder(dim=32)
    e = ApiEmbedder(url="", fallback=fallback)
    assert e.embed(["some text"]) == fallback.embed(["some text"])


def test_api_embedder_degrades_on_transport_error() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        raise urllib.error.URLError("down")

    fallback = HashingEmbedder(dim=16)
    e = ApiEmbedder(url="http://x", poster=boom, fallback=fallback)
    assert e.embed(["t"]) == fallback.embed(["t"])


def test_api_embedder_degrades_on_length_mismatch() -> None:
    # Server returns fewer rows than inputs — must degrade whole, never misalign.
    def short(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        return json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode()

    fallback = HashingEmbedder(dim=8)
    e = ApiEmbedder(url="http://x", poster=short, fallback=fallback)
    out = e.embed(["a", "b", "c"])
    assert out == fallback.embed(["a", "b", "c"])


def test_api_embedder_reorders_by_index() -> None:
    def scrambled(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        rows = [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]
        return json.dumps({"data": rows}).encode()

    e = ApiEmbedder(url="http://x", poster=scrambled)
    out = e.embed(["first", "second"])
    assert out[0] == pytest.approx((1.0, 0.0))
    assert out[1] == pytest.approx((0.0, 1.0))


def test_api_embedder_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def counting(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        req = json.loads(body)
        calls.append(len(req["input"]))
        rows = [{"index": i, "embedding": [1.0]} for i in range(len(req["input"]))]
        return json.dumps({"data": rows}).encode()

    e = ApiEmbedder(url="http://x", poster=counting, batch=2)
    e.embed(["a", "b", "c", "d", "e"])
    assert calls == [2, 2, 1]


def test_api_embedder_sends_authorization_when_keyed() -> None:
    seen: dict[str, str] = {}

    def capture(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.update(headers)
        return json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode()

    ApiEmbedder(url="http://x", api_key="secret", poster=capture).embed(["t"])
    assert seen.get("Authorization") == "Bearer secret"


# --- CachingEmbedder ---------------------------------------------------------


def test_caching_embeds_once_per_unique_text(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class Counting:
        def embed(self, texts):
            calls.append(list(texts))
            return [(float(len(t)),) for t in texts]

    cached = CachingEmbedder(Counting(), tmp_path, tag="m")
    assert cached.embed(["ab", "cde"]) == [(2.0,), (3.0,)]
    # Second call: all hits, delegate not touched again.
    assert cached.embed(["ab", "cde"]) == [(2.0,), (3.0,)]
    assert calls == [["ab", "cde"]]


def test_caching_only_calls_delegate_for_misses(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class Counting:
        def embed(self, texts):
            calls.append(list(texts))
            return [(float(len(t)),) for t in texts]

    cached = CachingEmbedder(Counting(), tmp_path)
    cached.embed(["ab"])
    cached.embed(["ab", "cde"])  # only "cde" is a miss
    assert calls == [["ab"], ["cde"]]


def test_caching_tag_namespaces_entries(tmp_path: Path) -> None:
    class Fixed:
        def __init__(self, value: float) -> None:
            self.value = value

        def embed(self, texts):
            return [(self.value,) for _ in texts]

    a = CachingEmbedder(Fixed(1.0), tmp_path, tag="model-a")
    b = CachingEmbedder(Fixed(2.0), tmp_path, tag="model-b")
    assert a.embed(["x"]) == [(1.0,)]
    assert b.embed(["x"]) == [(2.0,)]  # different tag → not served a's vector
