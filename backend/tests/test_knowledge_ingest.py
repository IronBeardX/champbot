import asyncio

import pytest

from champbot.common.embeddings.domain.embedder import EmbeddingError
from champbot.common.vector_store.domain.store import Chunk
from champbot.knowledge.ingest.application.ingest import ingest_chunks
from champbot.knowledge.ingest.domain.chunker import DocumentChunk


class FakeEmbedder:
    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._vectors_by_text = vectors_by_text
        self.received_texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.received_texts = texts
        return [self._vectors_by_text[text] for text in texts]


class FailingEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("boom")


class ShortEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0]]


class FakeVectorStore:
    def __init__(self, mutation_ids: list[str]) -> None:
        self._mutation_ids = mutation_ids
        self.upserted: list[Chunk] = []

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        self.upserted = chunks
        return self._mutation_ids


def make_chunk(suffix: int) -> DocumentChunk:
    return DocumentChunk(
        id=f"policy-{suffix}",
        title="Title",
        source_url="https://www.airindia.com/policy",
        section="Section",
        text="Body text",
    )


def test_embeds_the_embedding_text_not_the_raw_text() -> None:
    chunk = make_chunk(1)
    embedder = FakeEmbedder({chunk.embedding_text: [0.1, 0.2]})
    store = FakeVectorStore(["mutation-1"])

    asyncio.run(ingest_chunks([chunk], embedder, store))

    assert embedder.received_texts == [chunk.embedding_text]


def test_upserts_chunks_with_the_document_chunk_id_and_metadata() -> None:
    chunk = make_chunk(1)
    embedder = FakeEmbedder({chunk.embedding_text: [0.1, 0.2]})
    store = FakeVectorStore(["mutation-1"])

    asyncio.run(ingest_chunks([chunk], embedder, store))

    assert store.upserted == [Chunk(id=chunk.id, vector=[0.1, 0.2], metadata=chunk.metadata)]


def test_an_embedding_error_propagates_and_upsert_is_never_called() -> None:
    chunk = make_chunk(1)
    store = FakeVectorStore(["unused"])

    with pytest.raises(EmbeddingError):
        asyncio.run(ingest_chunks([chunk], FailingEmbedder(), store))

    assert store.upserted == []


def test_a_vector_count_mismatch_raises_before_any_upsert() -> None:
    chunks = [make_chunk(1), make_chunk(2)]
    store = FakeVectorStore(["unused"])

    with pytest.raises(EmbeddingError):
        asyncio.run(ingest_chunks(chunks, ShortEmbedder(), store))

    assert store.upserted == []


def test_the_report_carries_the_chunk_count_and_the_store_mutation_ids() -> None:
    chunks = [make_chunk(1), make_chunk(2)]
    embedder = FakeEmbedder({chunk.embedding_text: [0.1] for chunk in chunks})
    store = FakeVectorStore(["mutation-1"])

    report = asyncio.run(ingest_chunks(chunks, embedder, store))

    assert report.chunk_count == 2
    assert report.mutation_ids == ["mutation-1"]
