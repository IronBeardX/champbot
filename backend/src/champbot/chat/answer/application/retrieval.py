import logging

from champbot.common.embeddings.domain.embedder import Embedder, EmbeddingError
from champbot.common.vector_store.domain.store import ScoredChunk, VectorStore

DEFAULT_TOP_K = 5

logger = logging.getLogger(__name__)


async def retrieve_policy_chunks(
    query_text: str,
    embedder: Embedder,
    vector_store: VectorStore,
    *,
    min_score: float,
    top_k: int = DEFAULT_TOP_K,
) -> list[ScoredChunk]:
    vectors = await embedder.embed([query_text])
    if len(vectors) != 1:
        raise EmbeddingError(f"embedder returned {len(vectors)} vectors for 1 query")

    matches = await vector_store.query(vectors[0], top_k)
    logger.info(
        "retrieval matches: %s",
        [(match.id, round(match.score, 4)) for match in matches],
    )
    return [match for match in matches if match.score >= min_score]
