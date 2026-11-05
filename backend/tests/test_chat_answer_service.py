import asyncio
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import pytest

from champbot.chat.answer.application.flight_results import render_flights_prompt
from champbot.chat.answer.application.services import (
    PolicySource,
    answer_chat,
    build_retrieval_query,
    cited_sources,
    parse_structured_answer,
    render_policy_context,
    usable_chunks,
)
from champbot.chat.answer.domain.structured_answer import STRUCTURED_ANSWER_SCHEMA
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.chat.common.domain.rag_prompt import NO_POLICY_CONTEXT
from champbot.chat.common.domain.routing_prompt import ROUTING_PROMPT
from champbot.common.flights.domain.flight import Cabin, Flight
from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import LLMUnavailableError
from champbot.common.vector_store.domain.store import Chunk, ScoredChunk

FIXED_TODAY = date(2026, 11, 5)


class FakeProvider:
    def __init__(
        self,
        answer: str = "ok",
        *,
        intent: str = "general",
        flight_query: Mapping[str, Any] | None = None,
        source_ids: list[int] | None = None,
        raw: str | None = None,
    ) -> None:
        self.answer = answer
        self.intent = intent
        self.flight_query = flight_query
        self.source_ids = source_ids if source_ids is not None else []
        self.raw = raw
        self.calls: list[tuple[list[Message], str | None]] = []
        self.response_schemas: list[Mapping[str, Any] | None] = []

    async def generate(
        self,
        messages: list[Message],
        system_instruction: str | None = None,
        *,
        response_schema: Mapping[str, Any] | None = None,
    ) -> str:
        self.calls.append((messages, system_instruction))
        self.response_schemas.append(response_schema)
        if self.raw is not None:
            return self.raw
        return json.dumps(
            {
                "intent": self.intent,
                "flight_query": self.flight_query,
                "answer": self.answer,
                "source_ids": self.source_ids,
            }
        )


class FakeFlightSearch:
    def __init__(self, flights: list[Flight] | None = None) -> None:
        self.flights = flights if flights is not None else []
        self.calls: list[tuple[str, str, date]] = []

    async def search(self, origin: str, destination: str, departure_date: date) -> list[Flight]:
        self.calls.append((origin, destination, departure_date))
        return self.flights


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


class FakeVectorStore:
    def __init__(self, matches: list[ScoredChunk]) -> None:
        self._matches = matches

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        return self._matches

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise NotImplementedError


def make_chunk(
    suffix: int,
    score: float,
    *,
    title: str = "Title",
    section: str = "Section",
    text: str | None = "Body",
) -> ScoredChunk:
    metadata = {
        "title": title,
        "section": section,
        "source_url": f"https://www.airindia.com/policy-{suffix}",
    }
    if text is not None:
        metadata["text"] = text
    return ScoredChunk(id=f"chunk-{suffix}", score=score, metadata=metadata)


def test_build_retrieval_query_uses_only_the_message_with_no_history() -> None:
    messages = [Message(Role.USER, "Can I change my flight?")]

    assert build_retrieval_query(messages) == "Can I change my flight?"


def test_build_retrieval_query_joins_previous_and_latest_user_turns() -> None:
    messages = [
        Message(Role.USER, "What is the baggage allowance?"),
        Message(Role.ASSISTANT, "Economy gets 23kg."),
        Message(Role.USER, "What about business class?"),
    ]

    assert (
        build_retrieval_query(messages)
        == "What is the baggage allowance?\nWhat about business class?"
    )


def test_build_retrieval_query_ignores_older_user_turns() -> None:
    messages = [
        Message(Role.USER, "turn one"),
        Message(Role.ASSISTANT, "answer one"),
        Message(Role.USER, "turn two"),
        Message(Role.ASSISTANT, "answer two"),
        Message(Role.USER, "turn three"),
    ]

    assert build_retrieval_query(messages) == "turn two\nturn three"


def test_usable_chunks_skips_chunk_missing_text() -> None:
    chunks = [make_chunk(1, 0.9, text=None)]

    assert usable_chunks(chunks) == []


def test_usable_chunks_skips_chunk_missing_source_url() -> None:
    chunk = ScoredChunk(id="chunk-1", score=0.9, metadata={"title": "Baggage", "text": "x"})

    assert usable_chunks([chunk]) == []


def test_usable_chunks_keeps_rank_order() -> None:
    first = make_chunk(1, 0.9)
    second = make_chunk(2, 0.8)

    assert usable_chunks([first, second]) == [first, second]


def test_render_policy_context_numbers_chunks_in_rank_order() -> None:
    usable = [
        make_chunk(1, 0.9, title="Baggage", text="first body"),
        make_chunk(2, 0.8, title="Check-in", text="second body"),
    ]

    context = render_policy_context(usable)

    assert "[1] Baggage" in context
    assert "first body" in context
    assert "[2] Check-in" in context
    assert "second body" in context
    assert context.index("[1]") < context.index("[2]")


def test_render_policy_context_falls_back_when_nothing_usable() -> None:
    assert render_policy_context([]) == NO_POLICY_CONTEXT


def test_render_policy_context_renders_literal_braces_verbatim() -> None:
    usable = [make_chunk(1, 0.9, text="Fees are {variable} per kg")]

    assert "Fees are {variable} per kg" in render_policy_context(usable)


def test_cited_sources_returns_only_the_cited_chunk() -> None:
    usable = [make_chunk(1, 0.9, title="Baggage"), make_chunk(2, 0.8, title="Check-in")]

    assert cited_sources(usable, [2]) == [
        PolicySource(title="Check-in", url=usable[1].metadata["source_url"])
    ]


def test_cited_sources_deduplicates_and_sorts_by_rank() -> None:
    usable = [make_chunk(1, 0.9, title="Baggage"), make_chunk(2, 0.8, title="Check-in")]

    assert cited_sources(usable, [2, 2, 1]) == [
        PolicySource(title="Baggage", url=usable[0].metadata["source_url"]),
        PolicySource(title="Check-in", url=usable[1].metadata["source_url"]),
    ]


def test_cited_sources_drops_duplicate_and_out_of_range_ids() -> None:
    usable = [make_chunk(1, 0.9), make_chunk(2, 0.8), make_chunk(3, 0.7)]

    assert cited_sources(usable, [0, 7, -1]) == []


def test_cited_sources_deduplicates_two_cited_chunks_sharing_a_url() -> None:
    chunk_a = make_chunk(1, 0.9, title="Baggage")
    chunk_b = ScoredChunk(
        id="chunk-1b",
        score=0.8,
        metadata={
            "title": "Baggage again",
            "source_url": chunk_a.metadata["source_url"],
            "text": "x",
        },
    )
    usable = [chunk_a, chunk_b]

    assert cited_sources(usable, [1, 2]) == [
        PolicySource(title="Baggage", url=chunk_a.metadata["source_url"])
    ]


def test_cited_sources_empty_when_no_ids_cited() -> None:
    usable = [make_chunk(1, 0.9)]

    assert cited_sources(usable, []) == []


def test_cited_sources_numbering_skips_chunks_usable_chunks_dropped() -> None:
    chunks = [
        ScoredChunk(id="chunk-1", score=0.9, metadata={"title": "No text", "source_url": "x"}),
        make_chunk(2, 0.8, title="Baggage"),
    ]
    usable = usable_chunks(chunks)

    assert cited_sources(usable, [1]) == [
        PolicySource(title="Baggage", url=usable[0].metadata["source_url"])
    ]


def test_parse_structured_answer_parses_a_valid_payload() -> None:
    raw = json.dumps(
        {"intent": "policy", "flight_query": None, "answer": "23kg.", "source_ids": [1]}
    )

    parsed = parse_structured_answer(raw)

    assert parsed.intent == "policy"
    assert parsed.flight_query is None
    assert parsed.answer == "23kg."
    assert parsed.source_ids == [1]


def test_parse_structured_answer_raises_unavailable_error_on_invalid_json() -> None:
    with pytest.raises(LLMUnavailableError) as error:
        parse_structured_answer("not json")

    assert error.value.__cause__ is None


def test_parse_structured_answer_raises_unavailable_error_on_schema_violation() -> None:
    raw = json.dumps({"intent": "not-a-real-intent", "answer": "Hi", "source_ids": []})

    with pytest.raises(LLMUnavailableError) as error:
        parse_structured_answer(raw)

    assert error.value.__cause__ is None
    assert "not-a-real-intent" not in str(error.value)


def test_answer_chat_prepends_rag_context_to_the_persona() -> None:
    chunks = [make_chunk(1, 0.9, title="Baggage", text="baggage body")]
    provider = FakeProvider(answer="Here is the policy.", intent="policy", source_ids=[1])
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(
            messages,
            provider,
            FakeEmbedder(),
            FakeVectorStore(chunks),
            flight_search=FakeFlightSearch(),
            min_score=0.0,
            today=FIXED_TODAY,
        )
    )

    assert len(provider.calls) == 1
    sent_messages, system_instruction = provider.calls[0]
    assert sent_messages == messages
    assert system_instruction is not None
    assert system_instruction.startswith(ASSISTANT_SYSTEM_PROMPT)
    assert ROUTING_PROMPT in system_instruction
    assert render_flights_prompt(FIXED_TODAY) in system_instruction
    assert system_instruction.index(ROUTING_PROMPT) < system_instruction.index(
        render_flights_prompt(FIXED_TODAY)
    )
    assert "[1] Baggage" in system_instruction
    assert "baggage body" in system_instruction
    assert provider.response_schemas == [STRUCTURED_ANSWER_SCHEMA]
    assert result.intent == "policy"
    assert result.answer == "Here is the policy."
    assert result.sources == [PolicySource(title="Baggage", url=chunks[0].metadata["source_url"])]
    assert result.flights == []


def test_answer_chat_uses_no_policy_context_when_nothing_kept() -> None:
    provider = FakeProvider()
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(
            messages,
            provider,
            FakeEmbedder(),
            FakeVectorStore([]),
            flight_search=FakeFlightSearch(),
            min_score=0.5,
            today=FIXED_TODAY,
        )
    )

    _, system_instruction = provider.calls[0]
    assert system_instruction is not None
    assert NO_POLICY_CONTEXT in system_instruction
    assert "[1]" not in system_instruction
    assert result.sources == []


def test_answer_chat_never_derives_sources_from_the_model_answer() -> None:
    chunks = [make_chunk(1, 0.9, title="Baggage")]
    provider = FakeProvider(
        answer="See https://not-a-real-source.example/policy, source [1], for details."
    )
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(
            messages,
            provider,
            FakeEmbedder(),
            FakeVectorStore(chunks),
            flight_search=FakeFlightSearch(),
            min_score=0.5,
            today=FIXED_TODAY,
        )
    )

    assert result.sources == []


def test_answer_chat_raises_unavailable_error_on_invalid_structured_answer() -> None:
    provider = FakeProvider(raw="not json")
    messages = [Message(Role.USER, "Hi")]

    with pytest.raises(LLMUnavailableError) as error:
        asyncio.run(
            answer_chat(
                messages,
                provider,
                FakeEmbedder(),
                FakeVectorStore([]),
                flight_search=FakeFlightSearch(),
                min_score=0.5,
                today=FIXED_TODAY,
            )
        )

    assert error.value.__cause__ is None


def test_answer_chat_does_not_search_when_intent_is_not_flight_search() -> None:
    provider = FakeProvider(
        answer="Economy gets 23kg.",
        intent="policy",
        flight_query={"origin": "DEL", "destination": "LHR", "date": "2026-11-06"},
    )
    messages = [Message(Role.USER, "What is the baggage allowance?")]
    flight_search = FakeFlightSearch()

    result = asyncio.run(
        answer_chat(
            messages,
            provider,
            FakeEmbedder(),
            FakeVectorStore([]),
            flight_search=flight_search,
            min_score=0.5,
            today=FIXED_TODAY,
        )
    )

    assert flight_search.calls == []
    assert result.answer == "Economy gets 23kg."
    assert result.flights == []


def test_answer_chat_searches_and_appends_flights_for_a_complete_flight_query() -> None:
    flight = Flight(
        flight_number="AI 111",
        origin="DEL",
        destination="LHR",
        departure=datetime(2026, 11, 6, 13, 30),
        arrival=datetime(2026, 11, 6, 18, 20),
        fares={Cabin.ECONOMY: 48000, Cabin.BUSINESS: 180000},
    )
    provider = FakeProvider(
        answer="Flights from Delhi to London on Friday 6 November 2026:",
        intent="flight_search",
        flight_query={"origin": "DEL", "destination": "LHR", "date": "2026-11-06"},
    )
    messages = [Message(Role.USER, "Flights from Delhi to London next Friday")]
    flight_search = FakeFlightSearch([flight])

    result = asyncio.run(
        answer_chat(
            messages,
            provider,
            FakeEmbedder(),
            FakeVectorStore([]),
            flight_search=flight_search,
            min_score=0.5,
            today=FIXED_TODAY,
        )
    )

    assert flight_search.calls == [("DEL", "LHR", date(2026, 11, 6))]
    assert result.flights == [flight]
    assert "AI 111" in result.answer
