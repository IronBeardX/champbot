from datetime import date

import pytest

from champbot.knowledge.ingest.domain.chunker import (
    MAX_CHUNK_TOKENS,
    MAX_ID_BYTES,
    MAX_METADATA_BYTES,
    chunk_document,
    estimate_tokens,
)
from champbot.knowledge.ingest.domain.document import (
    InvalidPolicyDocumentError,
    PolicyDocument,
    parse_policy_document,
)

DOC_SOURCE_URL = "https://www.airindia.com/in/en/example.html"


def make_doc(body: str, slug: str = "example-doc", title: str = "Example") -> PolicyDocument:
    return PolicyDocument(
        slug=slug,
        title=title,
        source_url=DOC_SOURCE_URL,
        retrieved_at=date(2026, 11, 4),
        body=body,
    )


# --- parse_policy_document -------------------------------------------------


def test_parse_policy_document_reads_front_matter_and_body() -> None:
    raw = (
        "---\n"
        "title: Checked Baggage\n"
        "source_url: https://www.airindia.com/checked.html\n"
        "retrieved_at: 2026-11-04\n"
        "---\n"
        "# Checked baggage\n"
        "Some text.\n"
    )

    doc = parse_policy_document("checked-baggage", raw)

    assert doc.slug == "checked-baggage"
    assert doc.title == "Checked Baggage"
    assert doc.source_url == "https://www.airindia.com/checked.html"
    assert doc.retrieved_at == date(2026, 11, 4)
    assert doc.body == "# Checked baggage\nSome text."


def test_parse_policy_document_rejects_missing_front_matter_block() -> None:
    with pytest.raises(InvalidPolicyDocumentError):
        parse_policy_document("example-doc", "# Checked baggage\nSome text.\n")


def test_parse_policy_document_rejects_unclosed_front_matter_block() -> None:
    raw = "---\ntitle: Checked Baggage\n# Checked baggage\n"

    with pytest.raises(InvalidPolicyDocumentError):
        parse_policy_document("example-doc", raw)


def test_parse_policy_document_rejects_missing_required_key() -> None:
    raw = "---\ntitle: Checked Baggage\nsource_url: https://example.com\n---\nBody\n"

    with pytest.raises(InvalidPolicyDocumentError):
        parse_policy_document("example-doc", raw)


def test_parse_policy_document_rejects_bad_retrieved_at() -> None:
    raw = "---\ntitle: T\nsource_url: https://example.com\nretrieved_at: not-a-date\n---\nBody\n"

    with pytest.raises(InvalidPolicyDocumentError):
        parse_policy_document("example-doc", raw)


def test_parse_policy_document_rejects_bad_slug() -> None:
    raw = "---\ntitle: T\nsource_url: https://example.com\nretrieved_at: 2026-11-04\n---\nBody\n"

    with pytest.raises(InvalidPolicyDocumentError):
        parse_policy_document("Not A Slug", raw)


# --- estimate_tokens ---------------------------------------------------------


def test_estimate_tokens_rounds_up_characters_over_four() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


# --- chunk_document: packing -------------------------------------------------


def test_chunk_document_packs_small_sections_into_one_chunk() -> None:
    doc = make_doc(
        "# Heading One\nShort text.\n\n## Heading Two\nMore short text.\n\n"
        "## Heading Three\nEven more short text.\n"
    )

    chunks = chunk_document(doc)

    assert len(chunks) == 1
    assert chunks[0].section == "Heading One; Heading Two; Heading Three"


def test_chunk_document_starts_a_new_chunk_on_overflow() -> None:
    doc = make_doc(f"# Section A\n{'a' * 1500}\n\n## Section B\n{'b' * 1500}\n")

    chunks = chunk_document(doc)

    assert len(chunks) == 2
    assert chunks[0].section == "Section A"
    assert chunks[1].section == "Section B"


def test_every_chunk_stays_at_or_under_the_token_ceiling() -> None:
    doc = make_doc(f"# Section A\n{'a' * 1500}\n\n## Section B\n{'b' * 1500}\n")

    for chunk in chunk_document(doc):
        assert estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS


def test_chunk_document_keeps_heading_lines_in_the_chunk_text() -> None:
    doc = make_doc("# Heading One\nSome text.\n\n## Heading Two\nMore text.\n")

    chunks = chunk_document(doc)

    assert "# Heading One" in chunks[0].text
    assert "## Heading Two" in chunks[0].text


def test_chunk_document_loses_no_content_from_the_body() -> None:
    doc = make_doc(f"# Section A\n{'a' * 1500}\n\n## Section B\n{'b' * 1500}\n")

    chunks = chunk_document(doc)
    reassembled = "\n".join(chunk.text for chunk in chunks)

    for line in doc.body.splitlines():
        if line.strip():
            assert line in reassembled


# --- chunk_document: oversized sections -------------------------------------


def test_oversized_section_is_split_at_paragraphs() -> None:
    paragraphs = "\n\n".join(f"Paragraph {i} " + "x" * 700 for i in range(4))
    doc = make_doc(f"# Big section\n{paragraphs}\n")

    chunks = chunk_document(doc)

    assert len(chunks) > 1
    for chunk in chunks:
        assert estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS
    for i in range(4):
        assert any(f"Paragraph {i} " in chunk.text for chunk in chunks)


def test_a_single_huge_line_is_hard_cut_under_the_ceiling() -> None:
    doc = make_doc(f"# Big section\n{'a' * 3000}\n")

    chunks = chunk_document(doc)

    assert len(chunks) > 1
    for chunk in chunks:
        assert estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS
    assert "".join(chunk.text for chunk in chunks).count("a") == 3000


# --- chunk_document: source_url override ------------------------------------


def test_source_override_applies_only_to_its_own_heading() -> None:
    checked_url = "https://www.airindia.com/checked-baggage.html"
    cabin_url = "https://www.airindia.com/cabin-baggage.html"
    doc = make_doc(
        f"# Checked baggage\n<!-- source_url: {checked_url} -->\nChecked text.\n\n"
        f"# Cabin baggage\n<!-- source_url: {cabin_url} -->\nCabin text.\n"
    )

    chunks = chunk_document(doc)

    checked_chunks = [chunk for chunk in chunks if "Checked text." in chunk.text]
    cabin_chunks = [chunk for chunk in chunks if "Cabin text." in chunk.text]
    assert all(chunk.source_url == checked_url for chunk in checked_chunks)
    assert all(chunk.source_url == cabin_url for chunk in cabin_chunks)


def test_source_override_comment_is_stripped_and_forces_a_boundary() -> None:
    doc = make_doc(
        "# Checked baggage\n<!-- source_url: https://example.com/checked.html -->\nChecked.\n\n"
        "# Cabin baggage\n<!-- source_url: https://example.com/cabin.html -->\nCabin.\n"
    )

    chunks = chunk_document(doc)

    assert all("source_url:" not in chunk.text for chunk in chunks)
    assert all("<!--" not in chunk.text for chunk in chunks)
    assert not any("Checked." in chunk.text and "Cabin." in chunk.text for chunk in chunks)


# --- chunk_document: ids and limits ------------------------------------------


def test_chunk_ids_are_sequential_and_unique() -> None:
    doc = make_doc("# One\nText.\n\n## Two\nText.\n\n## Three\nText.\n", slug="policy-doc")

    chunks = chunk_document(doc)

    assert [chunk.id for chunk in chunks] == [f"policy-doc-{i + 1}" for i in range(len(chunks))]


def test_chunk_document_raises_when_an_id_would_exceed_the_byte_limit() -> None:
    long_slug = "a" * 64
    doc = make_doc("# One\nShort text.\n", slug=long_slug)

    with pytest.raises(InvalidPolicyDocumentError):
        chunk_document(doc)


def test_chunk_document_raises_when_metadata_would_exceed_the_byte_limit() -> None:
    doc = make_doc("# One\nShort text.\n", title="x" * (MAX_METADATA_BYTES + 1))

    with pytest.raises(InvalidPolicyDocumentError):
        chunk_document(doc)


def test_an_id_within_the_limit_does_not_raise() -> None:
    slug = "a" * (MAX_ID_BYTES - 2)
    doc = make_doc("# One\nShort text.\n", slug=slug)

    chunk_document(doc)


# --- chunk_document: metadata and embedding text -----------------------------


def test_chunk_metadata_has_exactly_the_expected_keys() -> None:
    doc = make_doc("# One\nText.\n")

    chunk = chunk_document(doc)[0]

    assert set(chunk.metadata.keys()) == {"title", "source_url", "section", "text"}


def test_embedding_text_starts_with_title_and_section() -> None:
    doc = make_doc("# One\nText.\n")

    chunk = chunk_document(doc)[0]

    assert chunk.embedding_text.startswith(f"{chunk.title} > {chunk.section}")


def test_metadata_bytes_counts_utf8_bytes_not_characters() -> None:
    doc = make_doc("# One\nCafé résumé.\n")

    chunk = chunk_document(doc)[0]
    char_length = len(
        '{"title": "'
        + chunk.title
        + '", "source_url": "'
        + chunk.source_url
        + '", "section": "'
        + chunk.section
        + '", "text": "'
        + chunk.text
        + '"}'
    )

    assert chunk.metadata_bytes > char_length
