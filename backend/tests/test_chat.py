from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from champbot.chat.answer.presentation.dependencies import get_llm_provider
from champbot.chat.common.domain.assistant_prompt import ASSISTANT_SYSTEM_PROMPT
from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.main import create_app

INTERNAL_DETAIL = "upstream said: secret internals"
USER_MESSAGE = "Where is my lost suitcase?"


class FakeProvider:
    def __init__(self, answer: str = "", error: LLMError | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[list[Message], str | None]] = []

    async def generate(self, messages: list[Message], system_instruction: str | None = None) -> str:
        self.calls.append((messages, system_instruction))
        if self.error is not None:
            raise self.error
        return self.answer


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
    monkeypatch.delenv(missing_name)


def client_with(provider: FakeProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app)


def test_returns_provider_answer_for_the_message() -> None:
    provider = FakeProvider(answer="Yes, you can change it online.")

    response = client_with(provider).post("/chat", json={"message": "  Can I change my flight?"})

    assert response.status_code == 200
    assert response.json() == {"answer": "Yes, you can change it online."}
    assert provider.calls == [
        ([Message(Role.USER, "  Can I change my flight?")], ASSISTANT_SYSTEM_PROMPT)
    ]


def test_sends_the_assistant_prompt_as_system_instruction() -> None:
    provider = FakeProvider(answer="ok")

    client_with(provider).post("/chat", json={"message": USER_MESSAGE})

    assert ASSISTANT_SYSTEM_PROMPT.strip(), "a blank prompt would be silently dropped by Gemini"
    [(_, system_instruction)] = provider.calls
    assert system_instruction == ASSISTANT_SYSTEM_PROMPT


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
    assert provider.calls == [([Message(Role.USER, "a" * 2000)], ASSISTANT_SYSTEM_PROMPT)]


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
            ASSISTANT_SYSTEM_PROMPT,
        )
    ]


def test_explicit_empty_history_sends_only_the_message() -> None:
    provider = FakeProvider(answer="ok")

    response = client_with(provider).post("/chat", json={"message": USER_MESSAGE, "history": []})

    assert response.status_code == 200
    assert provider.calls == [([Message(Role.USER, USER_MESSAGE)], ASSISTANT_SYSTEM_PROMPT)]


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


@pytest.mark.parametrize("missing_name", ["GEMINI_API_KEY", "GEMINI_MODEL"])
@pytest.mark.usefixtures("no_network")
def test_missing_setting_returns_generic_json_500(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    configure_settings_without(monkeypatch, missing_name)

    response = TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code == 500
    assert_generic_error_body(response.json())
    assert missing_name not in response.text


@pytest.mark.parametrize("missing_name", ["GEMINI_API_KEY", "GEMINI_MODEL"])
@pytest.mark.usefixtures("no_network")
def test_missing_setting_is_logged_by_name_never_by_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, missing_name: str
) -> None:
    configure_settings_without(monkeypatch, missing_name)

    TestClient(create_app()).post("/chat", json={"message": USER_MESSAGE})

    assert missing_name in caplog.text
    assert "test-key" not in caplog.text
    assert "test-model" not in caplog.text


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

    response = TestClient(app).post("/chat", json={"message": USER_MESSAGE})

    assert response.status_code >= 400
    assert caplog.text
    assert "test-key" not in caplog.text
