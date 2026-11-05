import logging
from dataclasses import dataclass

from champbot.chat.answer.application.retrieval import DEFAULT_TOP_K, retrieve_policy_chunks
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.chat.common.domain.rag_prompt import NO_POLICY_CONTEXT, RAG_CHUNK, RAG_PROMPT
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import LLMProvider
from champbot.common.vector_store.domain.store import ScoredChunk, VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicySource:
    title: str
    url: str


@dataclass(frozen=True)
class ChatAnswer:
    answer: str
    sources: list[PolicySource]


async def answer_chat(
    messages: list[Message],
    provider: LLMProvider,
    embedder: Embedder,
    vector_store: VectorStore,
    *,
    min_score: float,
    top_k: int = DEFAULT_TOP_K,
) -> ChatAnswer:
    query_text = build_retrieval_query(messages)
    chunks = await retrieve_policy_chunks(
        query_text, embedder, vector_store, min_score=min_score, top_k=top_k
    )
    context = render_policy_context(chunks)
    system_instruction = f"{ASSISTANT_SYSTEM_PROMPT}\n{RAG_PROMPT.format(context=context)}"
    answer = await provider.generate(messages, system_instruction)
    return ChatAnswer(answer=answer, sources=build_sources(chunks))


def build_retrieval_query(messages: list[Message]) -> str:
    user_texts = [message.text for message in messages if message.role == Role.USER]
    return "\n".join(user_texts[-2:])


def render_policy_context(chunks: list[ScoredChunk]) -> str:
    usable = _usable_chunks(chunks)
    if not usable:
        return NO_POLICY_CONTEXT
    rendered = [
        RAG_CHUNK.format(
            number=number,
            title=chunk.metadata.get("title", ""),
            section=chunk.metadata.get("section", ""),
            text=chunk.metadata["text"],
        )
        for number, chunk in enumerate(usable, start=1)
    ]
    return "\n\n".join(rendered)


def build_sources(chunks: list[ScoredChunk]) -> list[PolicySource]:
    sources: list[PolicySource] = []
    seen_urls: set[str] = set()
    for chunk in _usable_chunks(chunks):
        url = chunk.metadata["source_url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(PolicySource(title=chunk.metadata.get("title", ""), url=url))
    return sources


def _usable_chunks(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    usable: list[ScoredChunk] = []
    for chunk in chunks:
        if not chunk.metadata.get("text") or not chunk.metadata.get("source_url"):
            logger.warning("skipping chunk %s: missing text or source_url metadata", chunk.id)
            continue
        usable.append(chunk)
    return usable
