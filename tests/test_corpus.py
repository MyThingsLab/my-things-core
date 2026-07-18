from pathlib import Path

import pytest

from mythings.corpus import (
    Chunk,
    Document,
    cached_extractor,
    chunk,
    cite,
    ingest,
    shortlist,
    tokenize,
)


def _doc(text: str, doc_id: str = "d", title: str = "D") -> Document:
    return Document(id=doc_id, path=f"/{doc_id}.txt", title=title, text=text)


def test_tokenize_lowercases_and_dedupes() -> None:
    assert tokenize("EM algorithm, EM Algorithm!") == {"em", "algorithm"}


def test_ingest_uses_injected_extractor_and_slugs_ids() -> None:
    docs = ingest(
        [Path("/books/Elements Of Statistical Learning.pdf")],
        extractor=lambda p: "body text",
        page_counter=lambda p: None,
    )
    assert len(docs) == 1
    assert docs[0].id == "elements-of-statistical-learning"
    assert docs[0].title == "Elements Of Statistical Learning"
    assert docs[0].text == "body text"


def test_ingest_disambiguates_colliding_slugs() -> None:
    docs = ingest(
        [Path("/a/Notes.pdf"), Path("/b/notes.pdf")],
        extractor=lambda p: "x",
        page_counter=lambda p: None,
    )
    assert [d.id for d in docs] == ["notes", "notes-2"]


def test_ingest_flags_a_sparse_scanned_pdf() -> None:
    # The #96 repro: 908 pages, 908 characters extracted -- ~1 char/page, an
    # image-only scan pdftotext could not read.
    docs = ingest(
        [Path("/books/scanned.pdf")],
        extractor=lambda p: "x" * 908,
        page_counter=lambda p: 908,
    )
    assert docs[0].sparse is True
    assert docs[0].text == "x" * 908  # #96: warn/flag, never drop or truncate


def test_ingest_does_not_flag_a_normal_pdf_as_sparse() -> None:
    docs = ingest(
        [Path("/books/normal.pdf")],
        extractor=lambda p: "prose " * 500,  # ~3000 chars over 10 pages
        page_counter=lambda p: 10,
    )
    assert docs[0].sparse is False


def test_ingest_treats_an_unknown_page_count_as_not_sparse() -> None:
    # page_counter returning None (pdfinfo unavailable/failed) must not be
    # mistaken for "confirmed sparse" -- no signal is not a positive signal.
    docs = ingest(
        [Path("/books/mystery.pdf")],
        extractor=lambda p: "x",
        page_counter=lambda p: None,
    )
    assert docs[0].sparse is False


def test_ingest_never_flags_a_non_pdf_as_sparse() -> None:
    docs = ingest([Path("/notes.txt")], extractor=lambda p: "x")
    assert docs[0].sparse is False


def test_cached_extractor_extracts_once_per_unchanged_file(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("body")
    calls: list[Path] = []

    def slow(path: Path) -> str:
        calls.append(path)
        return path.read_text()

    cached = cached_extractor(tmp_path / "cache", extractor=slow)
    assert cached(source) == "body"
    assert cached(source) == "body"
    assert len(calls) == 1


def test_cached_extractor_reextracts_when_the_file_changes(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("first")
    calls: list[Path] = []

    def extractor(path: Path) -> str:
        calls.append(path)
        return path.read_text()

    cached = cached_extractor(tmp_path / "cache", extractor=extractor)
    assert cached(source) == "first"
    # A stale cache that survives an edit is worse than no cache: the citation
    # spans would point into text the file no longer contains.
    source.write_text("second and longer")
    assert cached(source) == "second and longer"
    assert len(calls) == 2


def test_cached_extractor_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("body")
    cache = tmp_path / "cache"
    cached_extractor(cache, extractor=lambda p: "body")(source)
    assert [p.suffix for p in cache.iterdir()] == [".txt"]


def test_cached_extractor_does_not_touch_disk_until_used(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cached_extractor(cache)
    assert not cache.exists()


def test_chunk_spans_index_back_into_the_source_text() -> None:
    doc = _doc("alpha para\n\nbeta para\n\ngamma para")
    chunks = chunk(doc, target_chars=12)

    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        # The span is the contract citations rely on: it must reproduce the text.
        assert doc.text[c.start : c.end] == c.text
        assert c.text == c.text.strip()


def test_chunk_packs_paragraphs_up_to_target() -> None:
    doc = _doc("aaa\n\nbbb\n\nccc")
    assert [c.text for c in chunk(doc, target_chars=100)] == ["aaa\n\nbbb\n\nccc"]
    assert [c.text for c in chunk(doc, target_chars=8)] == ["aaa\n\nbbb", "ccc"]


def test_chunk_hard_splits_a_paragraph_wider_than_the_target() -> None:
    doc = _doc("x" * 25)
    chunks = chunk(doc, target_chars=10)
    assert [c.text for c in chunks] == ["x" * 10, "x" * 10, "x" * 5]
    assert doc.text[chunks[2].start : chunks[2].end] == "x" * 5


def test_chunk_flushes_pending_text_before_an_oversized_paragraph() -> None:
    doc = _doc("short\n\n" + "y" * 20)
    chunks = chunk(doc, target_chars=10)
    assert chunks[0].text == "short"
    assert [c.text for c in chunks[1:]] == ["y" * 10, "y" * 10]


def test_chunk_rejects_a_nonpositive_target() -> None:
    with pytest.raises(ValueError, match="target_chars"):
        chunk(_doc("text"), target_chars=0)


def test_shortlist_ranks_by_body_token_overlap() -> None:
    # The whole point of the seam: my-searcher scores paths and identifiers,
    # never body text. A chunk whose *text* matches must outrank one that doesn't.
    hit = Chunk(doc_id="d", ordinal=1, text="the EM algorithm maximizes likelihood", start=0, end=1)
    miss = Chunk(doc_id="d", ordinal=0, text="unrelated prose about kittens", start=1, end=2)

    assert shortlist([miss, hit], "EM algorithm", top=1) == [hit]


def test_shortlist_ties_break_deterministically_by_doc_then_ordinal() -> None:
    a2 = Chunk(doc_id="a", ordinal=2, text="em", start=0, end=1)
    a1 = Chunk(doc_id="a", ordinal=1, text="em", start=0, end=1)
    b0 = Chunk(doc_id="b", ordinal=0, text="em", start=0, end=1)

    assert shortlist([b0, a2, a1], "em") == [a1, a2, b0]


def test_shortlist_prefers_the_explaining_section_over_a_name_dropping_abstract() -> None:
    # The #90 defect. Set-based overlap scores these identically -- both contain
    # {ica}. The abstract wins on ordinal and buries the real section. Only term
    # frequency separates the passage that *explains* a term from the one that
    # merely lists it.
    abstract = Chunk(doc_id="d", ordinal=0, text="we review pca ica em hmm mcmc", start=0, end=1)
    section = Chunk(
        doc_id="d", ordinal=9, text="ica separates sources; ica assumes ica", start=0, end=1
    )
    filler = [
        Chunk(doc_id="d", ordinal=i, text="prose about models", start=0, end=1) for i in range(1, 9)
    ]

    assert shortlist([abstract, *filler, section], "ica", top=1) == [section]


def test_shortlist_downweights_a_token_common_to_every_chunk() -> None:
    # "algorithm" is everywhere, so it must not decide the ranking; the rare
    # "baum" must. Under bare overlap both chunks score 1 and ordinal decides.
    common = Chunk(doc_id="d", ordinal=0, text="algorithm algorithm algorithm", start=0, end=1)
    rare = Chunk(doc_id="d", ordinal=5, text="algorithm baum welch", start=0, end=1)
    filler = [
        Chunk(doc_id="d", ordinal=i, text="algorithm prose", start=0, end=1) for i in range(1, 5)
    ]

    assert shortlist([common, *filler, rare], "baum algorithm", top=1) == [rare]


def test_shortlist_downweights_a_reference_list_entry_over_the_explaining_section() -> None:
    # The #90 residual defect: a bibliography entry whose cited title repeats
    # the query words outranks the section that actually explains the term,
    # because TF-IDF alone rewards the repetition. boiler_ratio down-weights
    # navigation/reference-style lines (ending in a bare page number or dot
    # leaders) rather than excluding them, so the explaining section wins.
    reference = Chunk(
        doc_id="d",
        ordinal=135,
        text=(
            "Dempster, A. EM algorithm for mixtures. 1977 39\n"
            "Neal, R. EM algorithm variational view. 1998 355\n"
            "Ghahramani, Z. EM algorithm factor analyzers. 1997 89"
        ),
        start=0,
        end=1,
    )
    section = Chunk(
        doc_id="d",
        ordinal=32,
        text="the em algorithm alternates an e step and an m step to maximize the likelihood bound",
        start=0,
        end=1,
    )

    assert shortlist([reference, section], "EM algorithm", top=1) == [section]


def test_boiler_ratio_leaves_ordinary_prose_at_zero() -> None:
    from mythings.corpus import _boiler_ratio

    text = "the em algorithm alternates two steps.\nit converges to a local optimum."
    assert _boiler_ratio(text) == 0.0


def test_boiler_ratio_flags_dot_leader_and_page_number_lines() -> None:
    from mythings.corpus import _boiler_ratio

    text = "Chapter 3 . . . . . . 42\nAppendix B 108\nreal prose about the model"
    assert _boiler_ratio(text) > 0.5


def test_shortlist_scores_a_token_present_in_every_chunk_without_degrading() -> None:
    # Smoothed IDF keeps an all-chunks-match positive, so ties still break by
    # (doc_id, ordinal) rather than silently falling to the degrade path.
    chunks = [Chunk(doc_id="d", ordinal=i, text="em", start=0, end=1) for i in range(3)]
    assert shortlist(chunks, "em", top=2) == chunks[:2]


def test_shortlist_degrades_to_leading_chunks_when_nothing_scores() -> None:
    chunks = [Chunk(doc_id="d", ordinal=i, text="kittens", start=0, end=1) for i in range(5)]
    assert shortlist(chunks, "quantum chromodynamics", top=2) == chunks[:2]


def test_shortlist_degrades_when_the_query_has_no_usable_tokens() -> None:
    chunks = [Chunk(doc_id="d", ordinal=i, text="kittens", start=0, end=1) for i in range(3)]
    assert shortlist(chunks, "!!! ???", top=2) == chunks[:2]


class _StubEmbedder:
    # Maps exact texts to fixed vectors so a fusion test controls the semantic
    # signal without a real model — the corpus analog of NoopEngine.
    def __init__(self, table: dict[str, tuple[float, ...]]) -> None:
        self._table = table

    def embed(self, texts):
        return [self._table[t] for t in texts]


def test_shortlist_without_embedder_is_unchanged_lexical_behavior() -> None:
    # The behavior-preserving guarantee: passing no embedder is byte-for-byte
    # the original lexical path.
    hit = Chunk(doc_id="d", ordinal=1, text="the EM algorithm maximizes likelihood", start=0, end=1)
    miss = Chunk(doc_id="d", ordinal=0, text="unrelated prose about kittens", start=1, end=2)
    assert shortlist([miss, hit], "EM algorithm", top=1) == [hit]
    assert shortlist([miss, hit], "EM algorithm", top=1, embedder=None) == [hit]


def test_shortlist_hybrid_is_deterministic() -> None:
    q = "anomaly"
    c0 = Chunk(doc_id="d", ordinal=0, text="alpha beta", start=0, end=1)
    c1 = Chunk(doc_id="d", ordinal=1, text="gamma delta", start=0, end=1)
    stub = _StubEmbedder({q: (1.0, 0.0), c0.text: (0.4, 0.6), c1.text: (0.9, 0.1)})
    first = shortlist([c0, c1], q, top=2, embedder=stub)
    second = shortlist([c0, c1], q, top=2, embedder=stub)
    assert first == second


def test_shortlist_hybrid_surfaces_a_semantic_match_over_a_lexical_distractor() -> None:
    # semantic: the real answer, but shares no word with the query.
    # distractor: carries the query word yet is semantically unrelated.
    semantic = Chunk(doc_id="d", ordinal=0, text="outliers rare points", start=0, end=1)
    distractor = Chunk(doc_id="d", ordinal=1, text="anomaly kittens garden", start=0, end=1)
    stub = _StubEmbedder(
        {"anomaly": (1.0, 0.0), semantic.text: (1.0, 0.0), distractor.text: (0.0, 1.0)}
    )
    # Lexical alone picks the distractor (it has the query token); fusion with
    # the semantic signal flips the winner to the passage that actually answers.
    assert shortlist([semantic, distractor], "anomaly", top=1) == [distractor]
    assert shortlist([semantic, distractor], "anomaly", top=1, embedder=stub) == [semantic]


def test_cite_resolves_titles_and_renders_a_marker() -> None:
    doc = _doc("text", doc_id="ghahramani", title="Unsupervised Learning")
    chunks = chunk(doc, target_chars=100)

    citations = cite(chunks, [doc])
    assert citations[0].title == "Unsupervised Learning"
    assert citations[0].marker() == "[ghahramani:0]"


def test_cite_rejects_a_chunk_from_an_unknown_document() -> None:
    orphan = Chunk(doc_id="missing", ordinal=0, text="t", start=0, end=1)
    with pytest.raises(ValueError, match="unknown document"):
        cite([orphan], [_doc("text")])
