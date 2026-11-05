import logging
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from champbot.chat.answer.application.flight_results import (
    FlightReply,
    answer_flight_query,
    render_flights_prompt,
)
from champbot.chat.answer.application.retrieval import DEFAULT_TOP_K, retrieve_policy_chunks
from champbot.chat.answer.domain.structured_answer import (
    STRUCTURED_ANSWER_SCHEMA,
    Intent,
    StructuredAnswer,
)
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.chat.common.domain.rag_prompt import NO_POLICY_CONTEXT, RAG_CHUNK, RAG_PROMPT
from champbot.chat.common.domain.routing_prompt import ROUTING_PROMPT
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.flights.domain.flight import Flight
from champbot.common.flights.domain.search import FlightSearch
from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import LLMProvider, LLMUnavailableError
from champbot.common.vector_store.domain.store import ScoredChunk, VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicySource:
    title: str
    url: str


@dataclass(frozen=True)
class ChatAnswer:
    intent: Intent
    answer: str
    sources: list[PolicySource]
    flights: list[Flight]


async def answer_chat(
    messages: list[Message],
    provider: LLMProvider,
    embedder: Embedder,
    vector_store: VectorStore,
    *,
    flight_search: FlightSearch,
    min_score: float,
    today: date,
    top_k: int = DEFAULT_TOP_K,
) -> ChatAnswer:
    query_text = build_retrieval_query(messages)
    chunks = await retrieve_policy_chunks(
        query_text, embedder, vector_store, min_score=min_score, top_k=top_k
    )
    usable = usable_chunks(chunks)
    context = render_policy_context(usable)
    system_instruction = (
        f"{ASSISTANT_SYSTEM_PROMPT}\n{ROUTING_PROMPT}\n{render_flights_prompt(today)}\n"
        f"{RAG_PROMPT.format(context=context)}"
    )
    raw = await provider.generate(
        messages, system_instruction, response_schema=STRUCTURED_ANSWER_SCHEMA
    )
    parsed = parse_structured_answer(raw)
    if parsed.intent == "flight_search":
        reply = await answer_flight_query(parsed.answer, parsed.flight_query, flight_search, today)
    else:
        reply = FlightReply(parsed.answer, [])
    return ChatAnswer(
        intent=parsed.intent,
        answer=reply.answer,
        sources=cited_sources(usable, parsed.source_ids),
        flights=reply.flights,
    )


def build_retrieval_query(messages: list[Message]) -> str:
    user_texts = [message.text for message in messages if message.role == Role.USER]
    return "\n".join(user_texts[-2:])


def parse_structured_answer(raw: str) -> StructuredAnswer:
    try:
        return StructuredAnswer.model_validate_json(raw)
    except ValidationError:
        raise LLMUnavailableError("Gemini returned an invalid structured answer") from None


def render_policy_context(usable: list[ScoredChunk]) -> str:
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


def cited_sources(usable: list[ScoredChunk], source_ids: list[int]) -> list[PolicySource]:
    valid_ids = sorted({source_id for source_id in source_ids if 1 <= source_id <= len(usable)})
    sources: list[PolicySource] = []
    seen_urls: set[str] = set()
    for source_id in valid_ids:
        chunk = usable[source_id - 1]
        url = chunk.metadata["source_url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(PolicySource(title=chunk.metadata.get("title", ""), url=url))
    return sources


def usable_chunks(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    usable: list[ScoredChunk] = []
    for chunk in chunks:
        if not chunk.metadata.get("text") or not chunk.metadata.get("source_url"):
            logger.warning("skipping chunk %s: missing text or source_url metadata", chunk.id)
            continue
        usable.append(chunk)
    return usable
