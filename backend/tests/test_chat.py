import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from champbot.chat.answer.application.flight_results import render_flights_prompt
from champbot.chat.answer.presentation.dependencies import (
    RetrievalPorts,
    get_llm_provider,
    get_min_score,
    get_retrieval_ports,
    get_today,
)
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.chat.common.domain.rag_prompt import NO_POLICY_CONTEXT, RAG_PROMPT
from champbot.chat.common.domain.routing_prompt import ROUTING_PROMPT
from champbot.common.embeddings.domain.embedder import EmbeddingError, EmbeddingTimeoutError
from champbot.common.flights.domain.flight import Cabin, Flight
from champbot.common.flights.domain.search import FlightSearch
from champbot.common.flights.presentation.dependencies import get_flight_search
from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.common.vector_store.domain.store import (
    Chunk,
    ScoredChunk,
    VectorStoreError,
    VectorStoreTimeoutError,
)
from champbot.main import create_app

INTERNAL_DETAIL = "upstream said: secret internals"
USER_MESSAGE = "Where is my lost suitcase?"
FIXED_TODAY = date(2026, 11, 5)
NO_CONTEXT_SYSTEM_INSTRUCTION = (
    f"{ASSISTANT_SYSTEM_PROMPT}\n{ROUTING_PROMPT}\n{render_flights_prompt(FIXED_TODAY)}\n"
    f"{RAG_PROMPT.format(context=NO_POLICY_CONTEXT)}"
)


class FakeProvider:
    def __init__(
        self,
        answer: str = "",
        error: LLMError | None = None,
        *,
        intent: str = "general",
        flight_query: Mapping[str, Any] | None = None,
        source_ids: list[int] | None = None,
    ) -> None:
        self.answer = answer
        self.error = error
        self.intent = intent
        self.flight_query = flight_query
        self.source_ids = source_ids if source_ids is not None else []
        self.calls: list[tuple[list[Message], str | None]] = []

    async def generate(
        self,
        messages: list[Message],
        system_instruction: str | None = None,
        *,
        response_schema: Mapping[str, Any] | None = None,
    ) -> str:
        self.calls.append((messages, system_instruction))
        if self.error is not None:
            raise self.error
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

    async def search(self, origin: str, destination: str, departure_date: date) -> list[Flight]:
        return self.flights


class FakeEmbedder:
    def __init__(self, vector: list[float] | None = None, error: Exception | None = None) -> None:
        self._vector = vector if vector is not None else [0.1]
        self._error = error
        self.received_texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.received_texts = texts
        if self._error is not None:
            raise self._error
        return [self._vector]


class FakeVectorStore:
    def __init__(
        self, matches: list[ScoredChunk] | None = None, error: Exception | None = None
    ) -> None:
        self._matches = matches if matches is not None else []
        self._error = error

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        if self._error is not None:
            raise self._error
        return self._matches

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise NotImplementedError


def assert_generic_error_body(body: dict[str, Any]) -> None:
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)
    assert body["detail"]
    assert USER_MESSAGE not in body["detail"]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_: Any, **__: Any) -> httpx.Response:
        raise AssertionError("unit tests must not reach the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", fail)


def configure_settings_without(monkeypatch: pytest.MonkeyPatch, missing_name: str) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CF_RUNTIME_API_TOKEN", "test-token")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.5")
    monkeypatch.delenv(missing_name)


def client_with(
    provider: FakeProvider,
    *,
    chunks: list[ScoredChunk] | None = None,
    embedder: FakeEmbedder | None = None,
    vector_store: FakeVectorStore | None = None,
    flight_search: FlightSearch | None = None,
    min_score: float = 0.5,
    today: date = FIXED_TODAY,
) -> TestClient:
    app = create_app()
    ports = RetrievalPorts(
        embedder=embedder if embedder is not None else FakeEmbedder(),
        vector_store=vector_store if vector_store is not None else FakeVectorStore(matches=chunks),
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    app.dependency_overrides[get_retrieval_ports] = lambda: ports
    app.dependency_overrides[get_min_score] = lambda: min_score
    app.dependency_overrides[get_flight_search] = (
        lambda: flight_search if flight_search is not None else FakeFlightSearch()
    )
    app.dependency_overrides[get_today] = lambda: today
    return TestClient(app)


def test_returns_provider_answer_for_the_message() -> None:
    provider = FakeProvider(answer="Yes, you can change it online.")

    response = client_with(provider).post("/chat", json={"message": "  Can I change my flight?"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "general",
        "answer": "Yes, you can change it online.",
        "sources": [],
        "flights": [],
    }
    assert provider.calls == [
        ([Message(Role.USER, "  Can I change my flight?")], NO_CONTEXT_SYSTEM_INSTRUCTION)
    ]


def test_returns_the_intent_the_provider_chose() -> None:
    provider = FakeProvider(answer="Searching...", intent="flight_search")

    response = client_with(provider).post("/chat", json={"message": "flights to London"})

    assert response.status_code == 200
    assert response.json()["intent"] == "flight_search"


def test_flight_turn_returns_flights_in_the_flight_response_shape() -> None:
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

    response = client_with(provider, flight_search=FakeFlightSearch([flight])).post(
        "/chat", json={"message": "Flights from Delhi to London next Friday"}
    )

    assert response.status_code == 200
    assert response.json()["flights"] == [
        {
            "flight_number": "AI 111",
            "origin": "DEL",
            "destination": "LHR",
            "departure": "2026-11-06T13:30:00",
            "arrival": "2026-11-06T18:20:00",
            "fares": {"economy": 48000, "business": 180000},
            "currency": "INR",
        }
    ]


def test_non_flight_turn_returns_an_empty_flights_list() -> None:
    provider = FakeProvider(answer="Hi there!", intent="general")

    response = client_with(provider).post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["flights"] == []


def test_sends_the_assistant_prompt_as_system_instruction() -> None:
    provider = FakeProvider(answer="ok")

    client_with(provider).post("/chat", json={"message": USER_MESSAGE})

    assert ASSISTANT_SYSTEM_PROMPT.strip(), "a blank prompt would be silently dropped by Gemini"
    [(_, system_instruction)] = provider.calls
    assert system_instruction is not None
    assert system_instruction.startswith(ASSISTANT_SYSTEM_PROMPT)
    assert NO_POLICY_CONTEXT in system_instruction


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing"),
        pytest.param({"message": ""}, id="empty"),
        pytest.param({"message": " \n\t "}, id="blank"),
        pytest.param({"message": "a" * 2001}, id="too-long"),
        pytest.param({"message": 123}, id="not-a-string"),
    ],
)
def test_invalid_message_is_rejected_before_reaching_provider(body: dict[str, Any]) -> None:
    provider = FakeProvider(answer="unused")

    response = client_with(provider).post("/chat", json=body)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert provider.calls == []


def test_malformed_json_body_is_rejected_before_reaching_provider() -> None:
    provider = FakeProvider(answer="unused")

    response = client_with(provider).post(
        "/chat", content="{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert provider.calls == []


def test_message_at_max_length_is_accepted() -> None:
    provider = FakeProvider(answer="ok")

    response = client_with(provider).post("/chat", json={"message": "a" * 2000})

    assert response.status_code == 200
    assert provider.calls == [([Message(Role.USER, "a" * 2000)], NO_CONTEXT_SYSTEM_INSTRUCTION)]


def conversation(
    pairs: int, user_text: str = "hi", assistant_text: str = "ok"
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for _ in range(pairs):
        history.append({"role": "user", "text": user_text})
        history.append({"role": "assistant", "text": assistant_text})
    return history


def test_history_is_sent_before_the_message_in_order() -> None:
    provider = FakeProvider(answer="ok")
    history = [
        {"role": "user", "text": "My name is Ana."},
        {"role": "assistant", "text": "Nice to meet you, Ana."},
        {"role": "user", "text": "I fly to Lisbon."},
        {"role": "assistant", "text": "Noted, Lisbon it is."},
    ]

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    assert response.status_code == 200
    assert provider.calls == [
        (
            [
                Message(Role.USER, "My name is Ana."),
                Message(Role.ASSISTANT, "Nice to meet you, Ana."),
                Message(Role.USER, "I fly to Lisbon."),
                Message(Role.ASSISTANT, "Noted, Lisbon it is."),
                Message(Role.USER, USER_MESSAGE),
            ],
            NO_CONTEXT_SYSTEM_INSTRUCTION,
        )
    ]


def test_explicit_empty_history_sends_only_the_message() -> None:
    provider = FakeProvider(answer="ok")

    response = client_with(provider).post("/chat", json={"message": USER_MESSAGE, "history": []})

    assert response.status_code == 200
    assert provider.calls == [([Message(Role.USER, USER_MESSAGE)], NO_CONTEXT_SYSTEM_INSTRUCTION)]


@pytest.mark.parametrize(
    "history",
    [
        pytest.param("hi", id="not-a-list"),
        pytest.param([{"text": "hi"}], id="missing-role"),
        pytest.param([{"role": "system", "text": "hi"}], id="unknown-role"),
        pytest.param([{"role": "user"}], id="missing-text"),
        pytest.param([{"role": "user", "text": 123}], id="text-not-a-string"),
        pytest.param([{"role": "user", "text": "   "}], id="blank-user-text"),
        pytest.param([{"role": "user", "text": "a" * 2001}], id="user-text-too-long"),
        pytest.param([{"role": "assistant", "text": "   "}], id="blank-assistant-text"),
        pytest.param([{"role": "assistant", "text": "a" * 8001}], id="assistant-text-too-long"),
        pytest.param([{"role": "assistant", "text": "hi"}], id="starts-with-assistant"),
        pytest.param(
            [{"role": "user", "text": "hi"}, {"role": "user", "text": "hi2"}],
            id="two-users-in-a-row",
        ),
        pytest.param(
            [
                {"role": "user", "text": "hi"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "hi2"},
            ],
            id="odd-length-ending-in-user",
        ),
        pytest.param(conversation(11), id="too-many-items"),
        pytest.param(
            [{"role": "user", "text": "a" * 2000}, {"role": "assistant", "text": "a" * 2001}] * 9
            + [{"role": "user", "text": "a" * 2000}, {"role": "assistant", "text": "a" * 2001}],
            id="total-too-long",
        ),
    ],
)
def test_invalid_history_is_rejected_before_reaching_provider(history: object) -> None:
    provider = FakeProvider(answer="unused")

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert provider.calls == []


@pytest.mark.parametrize(
    ("history", "expected_phrase"),
    [
        pytest.param(
            [{"role": "assistant", "text": "hi"}],
            "must have role 'user'",
            id="alternation",
        ),
        pytest.param(
            [
                {"role": "user", "text": "hi"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "hi2"},
            ],
            "must end with an assistant turn",
            id="odd-length",
        ),
        pytest.param(
            [{"role": "user", "text": "a" * 2000}, {"role": "assistant", "text": "a" * 2001}] * 9
            + [{"role": "user", "text": "a" * 2000}, {"role": "assistant", "text": "a" * 2001}],
            "total at most 40000 characters",
            id="total-length",
        ),
    ],
)
def test_history_shape_errors_name_the_rule(
    history: list[dict[str, str]], expected_phrase: str
) -> None:
    response = client_with(FakeProvider(answer="unused")).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "history"]
    assert expected_phrase in detail[0]["msg"]


def test_user_history_item_at_max_length_is_accepted() -> None:
    provider = FakeProvider(answer="ok")
    history = [{"role": "user", "text": "a" * 2000}, {"role": "assistant", "text": "ok"}]

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    assert response.status_code == 200


def test_assistant_history_item_at_max_length_is_accepted() -> None:
    provider = FakeProvider(answer="ok")
    history = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "a" * 8000}]

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    assert response.status_code == 200


def test_history_at_max_item_count_is_accepted() -> None:
    provider = FakeProvider(answer="ok")

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": conversation(10)}
    )

    assert response.status_code == 200


def test_history_at_max_total_length_is_accepted() -> None:
    provider = FakeProvider(answer="ok")
    history = conversation(10, user_text="a" * 2000, assistant_text="a" * 2000)

    response = client_with(provider).post(
        "/chat", json={"message": USER_MESSAGE, "history": history}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        pytest.param(LLMTimeoutError(INTERNAL_DETAIL), 504, id="timeout"),
        pytest.param(LLMUnavailableError(INTERNAL_DETAIL), 502, id="unavailable"),
        pytest.param(
            LLMUnavailableError(f"{INTERNAL_DETAIL} about {USER_MESSAGE}"),
            502,
            id="unavailable-quoting-the-user",
        ),
    ],
)
def test_provider_errors_map_to_http_errors_without_internals(
    error: LLMError, status_code: int
) -> None:
    response = client_with(FakeProvider(error=error)).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == status_code
    assert_generic_error_body(response.json())
    assert INTERNAL_DETAIL not in response.text
    assert "Retry-After" not in response.headers


def test_rate_limit_with_unknown_delay_returns_429_without_retry_after() -> None:
    provider = FakeProvider(error=LLMRateLimitError(retry_after_seconds=None))

    response = client_with(provider).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 429
    assert "Retry-After" not in response.headers
    assert_generic_error_body(response.json())
    assert str(provider.error) not in response.text


@pytest.mark.parametrize(("seconds", "header"), [(37, "37"), (0, "0")])
def test_rate_limit_forwards_retry_after(seconds: int, header: str) -> None:
    provider = FakeProvider(error=LLMRateLimitError(retry_after_seconds=seconds))

    response = client_with(provider).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == header
    assert_generic_error_body(response.json())
    assert str(provider.error) not in response.text


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(LLMTimeoutError(INTERNAL_DETAIL), id="timeout"),
        pytest.param(LLMUnavailableError(INTERNAL_DETAIL), id="unavailable"),
        pytest.param(LLMRateLimitError(retry_after_seconds=37), id="rate-limit"),
    ],
)
def test_provider_error_cause_is_logged(caplog: pytest.LogCaptureFixture, error: LLMError) -> None:
    client_with(FakeProvider(error=error)).post("/chat", json={"message": USER_MESSAGE})

    assert str(error), "an empty message would make the next check pass trivially"
    assert str(error) in caplog.text


MISSING_SETTING_NAMES = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "CLOUDFLARE_ACCOUNT_ID",
    "CF_RUNTIME_API_TOKEN",
    "RETRIEVAL_MIN_SCORE",
]


@pytest.mark.parametrize("missing_name", MISSING_SETTING_NAMES)
@pytest.mark.usefixtures("no_network")
def test_missing_setting_returns_generic_json_500(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    configure_settings_without(monkeypatch, missing_name)

    response = TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 500
    assert_generic_error_body(response.json())
    assert missing_name not in response.text


@pytest.mark.parametrize("missing_name", MISSING_SETTING_NAMES)
@pytest.mark.usefixtures("no_network")
def test_missing_setting_is_logged_by_name_never_by_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, missing_name: str
) -> None:
    configure_settings_without(monkeypatch, missing_name)

    TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert missing_name in caplog.text
    assert "test-key" not in caplog.text
    assert "test-model" not in caplog.text
    assert "test-account" not in caplog.text
    assert "test-token" not in caplog.text


@pytest.mark.usefixtures("no_network")
def test_invalid_min_score_returns_generic_json_500(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_settings_without(monkeypatch, "RETRIEVAL_MIN_SCORE")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "abc")

    response = TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 500
    assert_generic_error_body(response.json())
    assert "abc" not in response.text


@pytest.mark.usefixtures("no_network")
def test_invalid_min_score_is_logged_by_name_never_by_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    configure_settings_without(monkeypatch, "RETRIEVAL_MIN_SCORE")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "abc")

    TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert "RETRIEVAL_MIN_SCORE" in caplog.text
    assert "abc" not in caplog.text


@pytest.mark.usefixtures("no_network")
def test_invalid_thinking_level_returns_generic_json_500(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_settings_without(monkeypatch, "RETRIEVAL_MIN_SCORE")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.5")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "FAST")

    response = TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 500
    assert_generic_error_body(response.json())
    assert "FAST" not in response.text


@pytest.mark.usefixtures("no_network")
def test_invalid_thinking_level_is_logged_by_name_never_by_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    configure_settings_without(monkeypatch, "RETRIEVAL_MIN_SCORE")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.5")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "FAST")

    TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert "GEMINI_THINKING_LEVEL" in caplog.text
    assert "FAST" not in caplog.text


def raise_read_timeout(_: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out")


def respond_with_status(code: int, status: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": {"status": status}})

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(raise_read_timeout, id="timeout"),
        pytest.param(respond_with_status(503, "UNAVAILABLE"), id="server-error"),
        pytest.param(respond_with_status(429, "RESOURCE_EXHAUSTED"), id="rate-limit"),
    ],
)
def test_gemini_failures_never_log_the_api_key(
    caplog: pytest.LogCaptureFixture, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    provider = GeminiProvider("test-key", "test-model", transport=httpx.MockTransport(handler))
    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    app.dependency_overrides[get_retrieval_ports] = lambda: RetrievalPorts(
        embedder=FakeEmbedder(), vector_store=FakeVectorStore()
    )
    app.dependency_overrides[get_min_score] = lambda: 0.5

    response = TestClient(app).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code >= 400
    assert caplog.text
    assert "test-key" not in caplog.text


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        pytest.param(EmbeddingTimeoutError(INTERNAL_DETAIL), 504, id="embedding-timeout"),
        pytest.param(EmbeddingError(INTERNAL_DETAIL), 502, id="embedding-unavailable"),
        pytest.param(VectorStoreTimeoutError(INTERNAL_DETAIL), 504, id="vector-store-timeout"),
        pytest.param(VectorStoreError(INTERNAL_DETAIL), 502, id="vector-store-unavailable"),
    ],
)
def test_retrieval_errors_map_to_http_errors_without_internals(
    error: Exception, status_code: int
) -> None:
    provider = FakeProvider(answer="unused")
    if isinstance(error, (EmbeddingError, EmbeddingTimeoutError)):
        embedder, vector_store = FakeEmbedder(error=error), FakeVectorStore()
    else:
        embedder, vector_store = FakeEmbedder(), FakeVectorStore(error=error)

    response = client_with(provider, embedder=embedder, vector_store=vector_store).post(
        "/chat", json={"message": USER_MESSAGE}
    )

    assert response.status_code == status_code
    assert_generic_error_body(response.json())
    assert INTERNAL_DETAIL not in response.text
    assert provider.calls == []


def test_sources_are_built_from_cited_chunks_and_deduplicated_by_url() -> None:
    chunks = [
        ScoredChunk(
            id="chunk-1",
            score=0.9,
            metadata={
                "title": "Checked baggage",
                "text": "23kg in economy",
                "source_url": "https://www.airindia.com/baggage",
            },
        ),
        ScoredChunk(
            id="chunk-2",
            score=0.8,
            metadata={
                "title": "Checked baggage (duplicate source)",
                "text": "more detail",
                "source_url": "https://www.airindia.com/baggage",
            },
        ),
    ]
    provider = FakeProvider(answer="You get 23kg in economy.", source_ids=[1, 2])

    response = client_with(provider, chunks=chunks).post(
        "/chat", json={"message": "What is my checked baggage allowance?"}
    )

    assert response.status_code == 200
    assert response.json()["sources"] == [
        {"title": "Checked baggage", "url": "https://www.airindia.com/baggage"}
    ]


def test_sources_are_empty_when_nothing_is_cited() -> None:
    chunks = [
        ScoredChunk(
            id="chunk-1",
            score=0.9,
            metadata={
                "title": "Checked baggage",
                "text": "23kg in economy",
                "source_url": "https://www.airindia.com/baggage",
            },
        )
    ]
    provider = FakeProvider(answer="I don't have that information.")

    response = client_with(provider, chunks=chunks).post(
        "/chat", json={"message": "Do you have a lounge access policy?"}
    )

    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_sources_are_empty_when_nothing_was_retrieved() -> None:
    provider = FakeProvider(answer="I don't have that information.")

    response = client_with(provider, chunks=[]).post(
        "/chat", json={"message": "Do you have a lounge access policy?"}
    )

    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_followup_turn_retrieval_query_includes_both_user_texts() -> None:
    embedder = FakeEmbedder()
    provider = FakeProvider(answer="ok")
    history = [
        {"role": "user", "text": "What is the baggage allowance?"},
        {"role": "assistant", "text": "23kg in economy."},
    ]

    client_with(provider, embedder=embedder).post(
        "/chat", json={"message": "What about business class?", "history": history}
    )

    assert embedder.received_texts == ["What is the baggage allowance?\nWhat about business class?"]
