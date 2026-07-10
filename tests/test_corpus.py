from pathlib import Path

import pytest

from mythings.corpus import (
    Chunk,
    Document,
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
    )
    assert len(docs) == 1
    assert docs[0].id == "elements-of-statistical-learning"
    assert docs[0].title == "Elements Of Statistical Learning"
    assert docs[0].text == "body text"


def test_ingest_disambiguates_colliding_slugs() -> None:
    docs = ingest(
        [Path("/a/Notes.pdf"), Path("/b/notes.pdf")],
        extractor=lambda p: "x",
    )
    assert [d.id for d in docs] == ["notes", "notes-2"]


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


def test_shortlist_degrades_to_leading_chunks_when_nothing_scores() -> None:
    chunks = [Chunk(doc_id="d", ordinal=i, text="kittens", start=0, end=1) for i in range(5)]
    assert shortlist(chunks, "quantum chromodynamics", top=2) == chunks[:2]


def test_shortlist_degrades_when_the_query_has_no_usable_tokens() -> None:
    chunks = [Chunk(doc_id="d", ordinal=i, text="kittens", start=0, end=1) for i in range(3)]
    assert shortlist(chunks, "!!! ???", top=2) == chunks[:2]


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
