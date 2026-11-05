import asyncio

from champbot.chat.answer.application.services import (
    PolicySource,
    answer_chat,
    build_retrieval_query,
    build_sources,
    render_policy_context,
)
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.chat.common.domain.rag_prompt import NO_POLICY_CONTEXT
from champbot.common.llm.domain.message import Message, Role
from champbot.common.vector_store.domain.store import Chunk, ScoredChunk


class FakeProvider:
    def __init__(self, answer: str = "ok") -> None:
        self.answer = answer
        self.calls: list[tuple[list[Message], str | None]] = []

    async def generate(self, messages: list[Message], system_instruction: str | None = None) -> str:
        self.calls.append((messages, system_instruction))
        return self.answer


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


def test_render_policy_context_numbers_chunks_in_rank_order() -> None:
    chunks = [
        make_chunk(1, 0.9, title="Baggage", text="first body"),
        make_chunk(2, 0.8, title="Check-in", text="second body"),
    ]

    context = render_policy_context(chunks)

    assert "[1] Baggage" in context
    assert "first body" in context
    assert "[2] Check-in" in context
    assert "second body" in context
    assert context.index("[1]") < context.index("[2]")


def test_render_policy_context_falls_back_when_nothing_kept() -> None:
    assert render_policy_context([]) == NO_POLICY_CONTEXT


def test_render_policy_context_renders_literal_braces_verbatim() -> None:
    chunks = [make_chunk(1, 0.9, text="Fees are {variable} per kg")]

    assert "Fees are {variable} per kg" in render_policy_context(chunks)


def test_render_policy_context_skips_chunk_missing_text() -> None:
    chunks = [make_chunk(1, 0.9, text=None)]

    assert render_policy_context(chunks) == NO_POLICY_CONTEXT


def test_build_sources_deduplicates_by_url_in_rank_order() -> None:
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
    chunk_c = make_chunk(2, 0.7, title="Check-in")

    sources = build_sources([chunk_a, chunk_b, chunk_c])

    assert sources == [
        PolicySource(title="Baggage", url=chunk_a.metadata["source_url"]),
        PolicySource(title="Check-in", url=chunk_c.metadata["source_url"]),
    ]


def test_build_sources_empty_when_nothing_kept() -> None:
    assert build_sources([]) == []


def test_build_sources_skips_chunk_missing_source_url() -> None:
    chunk = ScoredChunk(id="chunk-1", score=0.9, metadata={"title": "Baggage", "text": "x"})

    assert build_sources([chunk]) == []


def test_answer_chat_prepends_rag_context_to_the_persona() -> None:
    chunks = [make_chunk(1, 0.9, title="Baggage", text="baggage body")]
    provider = FakeProvider(answer="Here is the policy.")
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(messages, provider, FakeEmbedder(), FakeVectorStore(chunks), min_score=0.0)
    )

    assert len(provider.calls) == 1
    sent_messages, system_instruction = provider.calls[0]
    assert sent_messages == messages
    assert system_instruction is not None
    assert system_instruction.startswith(ASSISTANT_SYSTEM_PROMPT)
    assert "[1] Baggage" in system_instruction
    assert "baggage body" in system_instruction
    assert result.answer == "Here is the policy."
    assert result.sources == [PolicySource(title="Baggage", url=chunks[0].metadata["source_url"])]


def test_answer_chat_uses_no_policy_context_when_nothing_kept() -> None:
    provider = FakeProvider()
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(messages, provider, FakeEmbedder(), FakeVectorStore([]), min_score=0.5)
    )

    _, system_instruction = provider.calls[0]
    assert system_instruction is not None
    assert NO_POLICY_CONTEXT in system_instruction
    assert "[1]" not in system_instruction
    assert result.sources == []


def test_answer_chat_never_derives_sources_from_the_model_answer() -> None:
    provider = FakeProvider(answer="See https://not-a-real-source.example/policy for details.")
    messages = [Message(Role.USER, "What is the baggage allowance?")]

    result = asyncio.run(
        answer_chat(messages, provider, FakeEmbedder(), FakeVectorStore([]), min_score=0.5)
    )

    assert result.sources == []
