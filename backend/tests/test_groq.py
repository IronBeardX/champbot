import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import pytest

from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from champbot.common.llm.infrastructure.groq import GroqProvider

Handler = Callable[[httpx.Request], httpx.Response]

HELLO_CONVERSATION = (Message(Role.USER, "Hello"),)
GREETING_EXCHANGE = (Message(Role.USER, "Hello"), Message(Role.ASSISTANT, "Hi, how can I help?"))

SAMPLE_SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}}

TEST_GENERATE_CONTENT_URL = "https://api.groq.test/openai/v1/chat/completions"


def generate(
    handler: Handler,
    messages: Sequence[Message] = HELLO_CONVERSATION,
    system_instruction: str | None = None,
    *,
    response_schema: Mapping[str, Any] | None = None,
    thinking_level: str | None = None,
) -> str:
    provider = GroqProvider(
        "test-key",
        "test-model",
        TEST_GENERATE_CONTENT_URL,
        transport=httpx.MockTransport(handler),
        thinking_level=thinking_level,
    )
    return asyncio.run(
        provider.generate(list(messages), system_instruction, response_schema=response_schema)
    )


def answer_with_content(content: str, finish_reason: str = "stop") -> Handler:
    body = {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}
    return lambda _: httpx.Response(200, json=body)


def respond(status_code: int, body: Any) -> Handler:
    return lambda _: httpx.Response(status_code, json=body)


def respond_text(status_code: int, text: str) -> Handler:
    return lambda _: httpx.Response(status_code, text=text)


def rate_limited(retry_after: str) -> Handler:
    return lambda _: httpx.Response(
        429, headers={"retry-after": retry_after}, json={"error": {"code": "rate_limit_exceeded"}}
    )


def raise_error(error: Exception) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    return handler


def capture_request(
    messages: Sequence[Message],
    system_instruction: str | None = None,
    *,
    response_schema: Mapping[str, Any] | None = None,
    thinking_level: str | None = None,
) -> httpx.Request:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer_with_content("Hi")(request)

    generate(
        handler,
        messages,
        system_instruction,
        response_schema=response_schema,
        thinking_level=thinking_level,
    )
    [request] = requests
    return request


def capture_request_body(
    messages: Sequence[Message],
    system_instruction: str | None = None,
    *,
    response_schema: Mapping[str, Any] | None = None,
    thinking_level: str | None = None,
) -> dict[str, Any]:
    return json.loads(
        capture_request(
            messages,
            system_instruction,
            response_schema=response_schema,
            thinking_level=thinking_level,
        ).content
    )


def test_sends_user_message_to_configured_model_with_key_in_header() -> None:
    request = capture_request([Message(Role.USER, "Can I change my flight?")])

    assert request.method == "POST"
    assert str(request.url) == TEST_GENERATE_CONTENT_URL
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Can I change my flight?"}],
    }


def test_sends_conversation_in_order_mapping_each_role_regardless_of_position() -> None:
    body = capture_request_body(
        [
            Message(Role.ASSISTANT, "Hi, how can I help?"),
            Message(Role.USER, "Can I change my flight?"),
            Message(Role.ASSISTANT, "Yes, you can."),
            Message(Role.ASSISTANT, "Which booking is it?"),
        ]
    )

    assert body["messages"] == [
        {"role": "assistant", "content": "Hi, how can I help?"},
        {"role": "user", "content": "Can I change my flight?"},
        {"role": "assistant", "content": "Yes, you can."},
        {"role": "assistant", "content": "Which booking is it?"},
    ]


@pytest.mark.parametrize(
    "system_instruction",
    [
        pytest.param("You are an airline assistant.", id="plain"),
        pytest.param("  You are an airline assistant.\n", id="surrounding-whitespace"),
    ],
)
def test_sends_system_instruction_verbatim_when_given(system_instruction: str) -> None:
    body = capture_request_body(GREETING_EXCHANGE, system_instruction)

    assert body["messages"] == [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi, how can I help?"},
    ]


@pytest.mark.parametrize("system_instruction", [None, "", " \n\t "])
def test_omits_system_instruction_when_absent_or_blank(system_instruction: str | None) -> None:
    body = capture_request_body(GREETING_EXCHANGE, system_instruction)

    assert body["messages"] == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi, how can I help?"},
    ]


def test_sends_reasoning_effort_when_given() -> None:
    body = capture_request_body(HELLO_CONVERSATION, thinking_level="low")

    assert body["reasoning_effort"] == "low"


def test_omits_reasoning_effort_when_absent() -> None:
    body = capture_request_body(HELLO_CONVERSATION)

    assert "reasoning_effort" not in body


def test_sends_response_schema_as_strict_json_schema() -> None:
    body = capture_request_body(HELLO_CONVERSATION, response_schema=SAMPLE_SCHEMA)

    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "structured_response", "schema": SAMPLE_SCHEMA, "strict": False},
    }


def test_omits_response_format_without_schema() -> None:
    body = capture_request_body(HELLO_CONVERSATION)

    assert "response_format" not in body


def test_returns_the_message_content() -> None:
    assert generate(answer_with_content("Yes, you can.")) == "Yes, you can."


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_free_text_answer_is_returned_whatever_the_finish_reason(finish_reason: str) -> None:
    assert generate(answer_with_content("Yes, you", finish_reason)) == "Yes, you"


def test_schema_call_with_stop_finish_reason_returns_the_json_text() -> None:
    body = generate(
        answer_with_content('{"intent": "general"}', "stop"), response_schema=SAMPLE_SCHEMA
    )

    assert body == '{"intent": "general"}'


@pytest.mark.parametrize(
    "finish_reason",
    [
        pytest.param("length", id="length"),
        pytest.param("content_filter", id="content-filter"),
        pytest.param(None, id="missing"),
    ],
)
def test_schema_call_with_non_stop_finish_reason_raises_unavailable_error(
    finish_reason: str | None,
) -> None:
    message: dict[str, Any] = {"content": '{"intent": "general"}'}
    choice: dict[str, Any] = {"message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    body = {"choices": [choice]}

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(200, body), response_schema=SAMPLE_SCHEMA)

    assert '"intent"' not in str(error.value)


def test_uses_only_the_first_choice() -> None:
    body = {
        "choices": [
            {"message": {"content": "First answer"}},
            {"message": {"content": "Second answer"}},
        ]
    }

    assert generate(respond(200, body)) == "First answer"


@pytest.mark.parametrize(
    ("retry_after", "expected_seconds"),
    [
        pytest.param("37", 37, id="whole-seconds"),
        pytest.param("2.5", 3, id="fractional-rounds-up"),
        pytest.param("0", 0, id="zero"),
        pytest.param("37s", 37, id="duration-suffix"),
        pytest.param("9" * 300, 3600, id="capped-at-one-hour"),
        pytest.param("1" + "0" * 400 + "s", 3600, id="overflowing-capped-at-one-hour"),
    ],
)
def test_rate_limit_carries_retry_delay_rounded_up(retry_after: str, expected_seconds: int) -> None:
    with pytest.raises(LLMRateLimitError) as error:
        generate(rate_limited(retry_after))

    assert error.value.retry_after_seconds == expected_seconds
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(respond(429, {"error": {"code": "rate_limit_exceeded"}}), id="no-retry-after"),
        pytest.param(rate_limited("soon"), id="malformed-retry-after"),
        pytest.param(rate_limited("1" + "0" * 400), id="overflowing-without-duration-suffix"),
        pytest.param(respond_text(429, "<html>Too Many Requests</html>"), id="non-json-body"),
    ],
)
def test_rate_limit_without_usable_retry_delay_has_no_delay(handler: Handler) -> None:
    with pytest.raises(LLMRateLimitError) as error:
        generate(handler)

    assert error.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "timeout",
    [
        pytest.param(httpx.ConnectTimeout("timed out"), id="connect"),
        pytest.param(httpx.ReadTimeout("timed out"), id="read"),
        pytest.param(httpx.WriteTimeout("timed out"), id="write"),
        pytest.param(httpx.PoolTimeout("timed out"), id="pool"),
    ],
)
def test_timeout_raises_timeout_error(timeout: httpx.TimeoutException) -> None:
    with pytest.raises(LLMTimeoutError) as error:
        generate(raise_error(timeout))

    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(respond(503, {"error": {"type": "service_unavailable"}}), id="server-error"),
        pytest.param(respond(400, {"error": {"code": "invalid_request_error"}}), id="client-error"),
        pytest.param(raise_error(httpx.ConnectError("refused")), id="network-error"),
        pytest.param(respond(200, {"choices": []}), id="no-choices"),
        pytest.param(answer_with_content(""), id="empty-content"),
        pytest.param(respond_text(200, "not json"), id="invalid-json"),
        pytest.param(respond(200, {"choices": {"first": {}}}), id="choices-object"),
        pytest.param(respond(200, {"choices": [{"message": {}}]}), id="missing-content"),
    ],
)
def test_unusable_responses_raise_unavailable_error(handler: Handler) -> None:
    with pytest.raises(LLMUnavailableError) as error:
        generate(handler)

    assert "test-key" not in str(error.value)


def test_whole_request_is_bounded_by_the_timeout() -> None:
    async def slow_response(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hi"}}]})

    provider = GroqProvider(
        "test-key",
        "test-model",
        TEST_GENERATE_CONTENT_URL,
        transport=httpx.MockTransport(slow_response),
        timeout_seconds=0.05,
    )

    with pytest.raises(LLMTimeoutError):
        asyncio.run(provider.generate(list(HELLO_CONVERSATION)))


def test_missing_answer_error_never_echoes_model_text() -> None:
    body = {
        "choices": [
            {
                "finish_reason": "content_filter",
                "message": {"content": "secret blocked text"},
            }
        ]
    }

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(200, body), response_schema=SAMPLE_SCHEMA)

    assert "secret blocked text" not in str(error.value)
    assert "content_filter" in str(error.value)


def test_error_response_message_keeps_code_without_echoing_body() -> None:
    body = {
        "error": {
            "code": "invalid_request_error",
            "message": "Invalid value in 'secret user message'",
        }
    }

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(400, body))

    assert "400" in str(error.value)
    assert "invalid_request_error" in str(error.value)
    assert "secret user message" not in str(error.value)


def test_error_response_message_drops_a_code_that_is_not_a_code() -> None:
    body = {"error": {"code": "secret user message, not a code"}}

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(400, body))

    assert "400" in str(error.value)
    assert "secret user message" not in str(error.value)
