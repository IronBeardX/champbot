from dataclasses import dataclass

from champbot.common.embeddings.domain.embedder import Embedder, EmbeddingError
from champbot.common.vector_store.domain.store import Chunk, VectorStore
from champbot.knowledge.ingest.domain.chunker import DocumentChunk


@dataclass(frozen=True)
class IngestReport:
    chunk_count: int
    mutation_ids: list[str]


async def ingest_chunks(
    chunks: list[DocumentChunk], embedder: Embedder, vector_store: VectorStore
) -> IngestReport:
    vectors = await embedder.embed([chunk.embedding_text for chunk in chunks])
    if len(vectors) != len(chunks):
        raise EmbeddingError(f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks")

    upsertable = [
        Chunk(id=chunk.id, vector=vector, metadata=chunk.metadata)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    mutation_ids = await vector_store.upsert(upsertable)
    return IngestReport(chunk_count=len(chunks), mutation_ids=mutation_ids)
