import json
from dataclasses import dataclass
from pathlib import Path

from champbot.knowledge.ingest.domain.chunker import (
    MAX_CHUNK_TOKENS,
    MAX_ID_BYTES,
    MAX_METADATA_BYTES,
    DocumentChunk,
    chunk_document,
    estimate_tokens,
)
from champbot.knowledge.ingest.domain.document import PolicyDocument, parse_policy_document

DATA_DIR = Path(__file__).parents[1] / "data"
POLICIES_DIR = DATA_DIR / "policies"
EVAL_FILE = DATA_DIR / "eval" / "policy_questions.json"


@dataclass(frozen=True)
class _Corpus:
    documents: list[PolicyDocument]
    chunks: list[DocumentChunk]


def load_corpus() -> _Corpus:
    documents: list[PolicyDocument] = []
    chunks: list[DocumentChunk] = []
    for path in sorted(POLICIES_DIR.glob("*.md")):
        doc = parse_policy_document(path.stem, path.read_text())
        documents.append(doc)
        chunks.extend(chunk_document(doc))
    return _Corpus(documents=documents, chunks=chunks)


def test_corpus_has_between_six_and_ten_documents() -> None:
    corpus = load_corpus()

    assert 6 <= len(corpus.documents) <= 10


def test_every_corpus_document_parses() -> None:
    corpus = load_corpus()

    for doc in corpus.documents:
        assert doc.title
        assert doc.source_url.startswith("https://www.airindia.com/")


def test_chunk_ids_are_globally_unique() -> None:
    corpus = load_corpus()
    ids = [chunk.id for chunk in corpus.chunks]

    assert len(ids) == len(set(ids))


def test_every_chunk_stays_within_vectorize_limits() -> None:
    corpus = load_corpus()

    for chunk in corpus.chunks:
        assert len(chunk.id.encode()) <= MAX_ID_BYTES
        assert chunk.metadata_bytes <= MAX_METADATA_BYTES
        assert estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS


def test_every_chunk_source_url_is_a_real_airindia_link() -> None:
    corpus = load_corpus()

    for chunk in corpus.chunks:
        assert chunk.source_url.startswith("https://www.airindia.com/")


def test_eval_seed_has_expected_shape_and_valid_doc_references() -> None:
    corpus = load_corpus()
    slugs = {doc.slug for doc in corpus.documents}
    seed = json.loads(EVAL_FILE.read_text())
    by_language: dict[str, int] = {}

    assert 3 <= len(seed["off_topic_queries"]) <= 7
    for entry in seed["policy_questions"]:
        assert entry["question"].strip()
        assert entry["expected_doc"] in slugs
        assert entry["language"] in {"en", "hi"}
        by_language[entry["language"]] = by_language.get(entry["language"], 0) + 1
    for query in seed["off_topic_queries"]:
        assert query.strip()

    assert 10 <= by_language.get("en", 0) <= 15
    assert 3 <= by_language.get("hi", 0) <= 7


def test_eval_seed_covers_every_document() -> None:
    corpus = load_corpus()
    slugs = {doc.slug for doc in corpus.documents}
    seed = json.loads(EVAL_FILE.read_text())
    covered = {entry["expected_doc"] for entry in seed["policy_questions"]}

    assert covered == slugs
