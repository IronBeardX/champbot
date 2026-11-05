import asyncio
import logging

import pytest

from champbot.chat.answer.application.retrieval import DEFAULT_TOP_K, retrieve_policy_chunks
from champbot.common.embeddings.domain.embedder import EmbeddingError, EmbeddingTimeoutError
from champbot.common.vector_store.domain.store import (
    Chunk,
    ScoredChunk,
    VectorStoreError,
    VectorStoreTimeoutError,
)

SENTINEL_TEXT = "a very specific policy sentence that must never be logged"


class FakeEmbedder:
    def __init__(self, vector: list[float] | None = None, error: Exception | None = None) -> None:
        self._vector = vector if vector is not None else [0.1, 0.2]
        self._error = error
        self.received_texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.received_texts = texts
        if self._error is not None:
            raise self._error
        return [self._vector]


class ShortEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class FakeVectorStore:
    def __init__(
        self, matches: list[ScoredChunk] | None = None, error: Exception | None = None
    ) -> None:
        self._matches = matches if matches is not None else []
        self._error = error
        self.received: tuple[list[float], int] | None = None

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        self.received = (vector, top_k)
        if self._error is not None:
            raise self._error
        return self._matches

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise NotImplementedError


def make_match(suffix: int, score: float) -> ScoredChunk:
    return ScoredChunk(id=f"chunk-{suffix}", score=score, metadata={"text": SENTINEL_TEXT})


def retrieve(
    embedder: FakeEmbedder | ShortEmbedder,
    vector_store: FakeVectorStore,
    *,
    min_score: float = 0.5,
    top_k: int | None = None,
) -> list[ScoredChunk]:
    kwargs = {} if top_k is None else {"top_k": top_k}
    return asyncio.run(
        retrieve_policy_chunks(
            "what about business class?", embedder, vector_store, min_score=min_score, **kwargs
        )
    )


def test_embeds_exactly_the_query_text() -> None:
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    retrieve(embedder, vector_store)

    assert embedder.received_texts == ["what about business class?"]


def test_queries_with_the_embedded_vector_and_default_top_k() -> None:
    embedder = FakeEmbedder(vector=[0.3, 0.4])
    vector_store = FakeVectorStore()

    retrieve(embedder, vector_store)

    assert vector_store.received == ([0.3, 0.4], DEFAULT_TOP_K)


def test_explicit_top_k_is_forwarded() -> None:
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    retrieve(embedder, vector_store, top_k=3)

    assert vector_store.received is not None
    assert vector_store.received[1] == 3


def test_keeps_matches_at_or_above_min_score_and_drops_the_rest() -> None:
    matches = [make_match(1, 0.9), make_match(2, 0.5), make_match(3, 0.49)]
    vector_store = FakeVectorStore(matches=matches)

    kept = retrieve(FakeEmbedder(), vector_store, min_score=0.5)

    assert [chunk.id for chunk in kept] == ["chunk-1", "chunk-2"]


def test_preserves_store_order() -> None:
    matches = [make_match(1, 0.9), make_match(2, 0.8), make_match(3, 0.7)]
    vector_store = FakeVectorStore(matches=matches)

    kept = retrieve(FakeEmbedder(), vector_store, min_score=0.0)

    assert [chunk.id for chunk in kept] == ["chunk-1", "chunk-2", "chunk-3"]


def test_embedder_returning_wrong_vector_count_raises_before_querying() -> None:
    vector_store = FakeVectorStore()

    with pytest.raises(EmbeddingError):
        retrieve(ShortEmbedder(), vector_store)

    assert vector_store.received is None


def test_embedder_error_propagates() -> None:
    embedder = FakeEmbedder(error=EmbeddingTimeoutError("boom"))
    vector_store = FakeVectorStore()

    with pytest.raises(EmbeddingTimeoutError):
        retrieve(embedder, vector_store)


def test_vector_store_error_propagates() -> None:
    vector_store = FakeVectorStore(error=VectorStoreTimeoutError("boom"))

    with pytest.raises(VectorStoreTimeoutError):
        retrieve(FakeEmbedder(), vector_store)


def test_vector_store_base_error_propagates() -> None:
    vector_store = FakeVectorStore(error=VectorStoreError("boom"))

    with pytest.raises(VectorStoreError):
        retrieve(FakeEmbedder(), vector_store)


def test_log_line_has_ids_and_scores_but_never_chunk_text(caplog: pytest.LogCaptureFixture) -> None:
    matches = [make_match(1, 0.9123456)]
    vector_store = FakeVectorStore(matches=matches)

    with caplog.at_level(logging.INFO):
        retrieve(FakeEmbedder(), vector_store, min_score=0.0)

    assert "chunk-1" in caplog.text
    assert "0.9123" in caplog.text
    assert SENTINEL_TEXT not in caplog.text
    assert "what about business class?" not in caplog.text
