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
from champbot.common.llm.infrastructure.gemini import GeminiProvider

Handler = Callable[[httpx.Request], httpx.Response]

HELLO_CONVERSATION = (Message(Role.USER, "Hello"),)
GREETING_EXCHANGE = (Message(Role.USER, "Hello"), Message(Role.ASSISTANT, "Hi, how can I help?"))

SAMPLE_SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}}


def generate(
    handler: Handler,
    messages: Sequence[Message] = HELLO_CONVERSATION,
    system_instruction: str | None = None,
    *,
    response_schema: Mapping[str, Any] | None = None,
    thinking_level: str | None = None,
) -> str:
    provider = GeminiProvider(
        "test-key",
        "test-model",
        transport=httpx.MockTransport(handler),
        thinking_level=thinking_level,
    )
    return asyncio.run(
        provider.generate(list(messages), system_instruction, response_schema=response_schema)
    )


def answer_with_parts(*parts: dict[str, Any]) -> Handler:
    body = {
        "candidates": [
            {"finishReason": "STOP", "content": {"role": "model", "parts": list(parts)}}
        ]
    }
    return lambda _: httpx.Response(200, json=body)


def respond(status_code: int, body: Any) -> Handler:
    return lambda _: httpx.Response(status_code, json=body)


def rate_limited(retry_delay: str) -> Handler:
    details: list[dict[str, Any]] = [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": []},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay},
    ]
    return respond(
        429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    )


def respond_text(status_code: int, text: str) -> Handler:
    return lambda _: httpx.Response(status_code, text=text)


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
        return answer_with_parts({"text": "Hi"})(request)

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
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "test-key"
    assert json.loads(request.content) == {
        "contents": [{"role": "user", "parts": [{"text": "Can I change my flight?"}]}]
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

    assert body == {
        "contents": [
            {"role": "model", "parts": [{"text": "Hi, how can I help?"}]},
            {"role": "user", "parts": [{"text": "Can I change my flight?"}]},
            {"role": "model", "parts": [{"text": "Yes, you can."}]},
            {"role": "model", "parts": [{"text": "Which booking is it?"}]},
        ]
    }


@pytest.mark.parametrize(
    "system_instruction",
    [
        pytest.param("You are an airline assistant.", id="plain"),
        pytest.param("  You are an airline assistant.\n", id="surrounding-whitespace"),
    ],
)
def test_sends_system_instruction_verbatim_when_given(system_instruction: str) -> None:
    body = capture_request_body(GREETING_EXCHANGE, system_instruction)

    assert body == {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi, how can I help?"}]},
        ],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
    }


@pytest.mark.parametrize("system_instruction", [None, "", " \n\t "])
def test_omits_system_instruction_when_absent_or_blank(system_instruction: str | None) -> None:
    body = capture_request_body(GREETING_EXCHANGE, system_instruction)

    assert body == {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi, how can I help?"}]},
        ]
    }


def test_joins_text_parts_and_skips_thoughts() -> None:
    handler = answer_with_parts(
        {"text": "Planning the reply", "thought": True},
        {"text": "Yes, ", "thoughtSignature": "abc"},
        {"text": "you can.", "thought": False},
    )

    assert generate(handler) == "Yes, you can."


@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY"])
def test_free_text_answer_is_returned_whatever_the_finish_reason(finish_reason: str) -> None:
    body = {
        "candidates": [
            {"finishReason": finish_reason, "content": {"parts": [{"text": "Yes, you"}]}}
        ]
    }

    assert generate(respond(200, body)) == "Yes, you"


def test_sends_response_schema_and_thinking_config_in_generation_config() -> None:
    body = capture_request_body(
        HELLO_CONVERSATION, response_schema=SAMPLE_SCHEMA, thinking_level="LOW"
    )

    assert body["generationConfig"] == {
        "thinkingConfig": {"thinkingLevel": "LOW"},
        "responseMimeType": "application/json",
        "responseJsonSchema": SAMPLE_SCHEMA,
    }


def test_sends_thinking_config_alone_when_no_schema_is_given() -> None:
    body = capture_request_body(HELLO_CONVERSATION, thinking_level="LOW")

    assert body["generationConfig"] == {"thinkingConfig": {"thinkingLevel": "LOW"}}


def test_omits_generation_config_without_schema_or_thinking_level() -> None:
    body = capture_request_body(HELLO_CONVERSATION)

    assert "generationConfig" not in body


def test_schema_call_with_stop_finish_reason_returns_the_json_text() -> None:
    body = {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": '{"intent": "general"}'}]}}
        ]
    }

    assert generate(respond(200, body), response_schema=SAMPLE_SCHEMA) == '{"intent": "general"}'


@pytest.mark.parametrize(
    "finish_reason",
    [
        pytest.param("MAX_TOKENS", id="max-tokens"),
        pytest.param("SAFETY", id="safety"),
        pytest.param("RECITATION", id="recitation"),
        pytest.param("OTHER", id="other"),
        pytest.param(None, id="missing"),
    ],
)
def test_schema_call_with_non_stop_finish_reason_raises_unavailable_error(
    finish_reason: str | None,
) -> None:
    candidate: dict[str, Any] = {"content": {"parts": [{"text": '{"intent": "general"}'}]}}
    if finish_reason is not None:
        candidate["finishReason"] = finish_reason
    body = {"candidates": [candidate]}

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(200, body), response_schema=SAMPLE_SCHEMA)

    assert '"intent"' not in str(error.value)


def test_uses_only_the_first_candidate() -> None:
    body = {
        "candidates": [
            {"content": {"parts": [{"text": "First answer"}]}},
            {"content": {"parts": [{"text": "Second answer"}]}},
        ]
    }

    assert generate(respond(200, body)) == "First answer"


@pytest.mark.parametrize(
    ("retry_delay", "expected_seconds"),
    [
        pytest.param("37s", 37, id="whole-seconds"),
        pytest.param("2.5s", 3, id="fractional-rounds-up"),
        pytest.param("0s", 0, id="zero"),
        pytest.param("9" * 300 + "s", 3600, id="capped-at-one-hour"),
        pytest.param("1" + "0" * 400 + "s", 3600, id="overflowing-capped-at-one-hour"),
    ],
)
def test_rate_limit_carries_retry_delay_rounded_up(retry_delay: str, expected_seconds: int) -> None:
    with pytest.raises(LLMRateLimitError) as error:
        generate(rate_limited(retry_delay))

    assert error.value.retry_after_seconds == expected_seconds
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(respond(429, {"error": {"code": 429}}), id="no-retry-info"),
        pytest.param(rate_limited("soon"), id="malformed-retry-delay"),
        pytest.param(respond_text(429, "<html>Too Many Requests</html>"), id="non-json-body"),
        pytest.param(
            respond(429, {"error": {"details": ["not-an-object"]}}), id="malformed-details"
        ),
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
        pytest.param(respond(503, {"error": {"status": "UNAVAILABLE"}}), id="server-error"),
        pytest.param(respond(400, {"error": {"status": "INVALID_ARGUMENT"}}), id="client-error"),
        pytest.param(raise_error(httpx.ConnectError("refused")), id="network-error"),
        pytest.param(raise_error(httpx.InvalidURL("bad model id")), id="invalid-url"),
        pytest.param(respond(200, {"candidates": []}), id="no-candidates"),
        pytest.param(
            respond(200, {"candidates": [{"finishReason": "SAFETY"}]}), id="blocked-answer"
        ),
        pytest.param(answer_with_parts({"text": "only thinking", "thought": True}), id="no-text"),
        pytest.param(respond_text(200, "not json"), id="invalid-json"),
        pytest.param(respond(200, {"candidates": {"first": {}}}), id="candidates-object"),
        pytest.param(
            respond(200, {"candidates": [{"content": {"parts": ["text"]}}]}), id="malformed-part"
        ),
    ],
)
def test_unusable_responses_raise_unavailable_error(handler: Handler) -> None:
    with pytest.raises(LLMUnavailableError) as error:
        generate(handler)

    assert "test-key" not in str(error.value)


def test_whole_request_is_bounded_by_the_timeout() -> None:
    async def slow_response(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})

    provider = GeminiProvider(
        "test-key", "test-model", transport=httpx.MockTransport(slow_response), timeout_seconds=0.05
    )

    with pytest.raises(LLMTimeoutError):
        asyncio.run(provider.generate(list(HELLO_CONVERSATION)))


@pytest.mark.parametrize(
    ("handler", "model_text", "reason_codes"),
    [
        pytest.param(
            answer_with_parts({"text": "secret model reasoning", "thought": True}),
            "secret model reasoning",
            [],
            id="thought-only-no-reason-codes",
        ),
        pytest.param(
            respond(200, {"candidates": [{"finishReason": "secret free text, not a code"}]}),
            "secret free text",
            [],
            id="finish-reason-not-a-code",
        ),
        pytest.param(
            respond(
                200,
                {
                    "candidates": [
                        {
                            "finishReason": "SAFETY",
                            "content": {
                                "parts": [{"text": "secret blocked text", "thought": True}]
                            },
                        }
                    ],
                    "promptFeedback": {"blockReason": "PROHIBITED_CONTENT"},
                },
            ),
            "secret blocked text",
            ["SAFETY", "PROHIBITED_CONTENT"],
            id="blocked",
        ),
    ],
)
def test_missing_answer_error_carries_reason_codes_and_never_model_text(
    handler: Handler, model_text: str, reason_codes: list[str]
) -> None:
    with pytest.raises(LLMUnavailableError) as error:
        generate(handler)

    assert model_text not in str(error.value)
    for reason_code in reason_codes:
        assert reason_code in str(error.value)


def test_error_response_message_keeps_status_without_echoing_body() -> None:
    body = {
        "error": {
            "code": 400,
            "status": "INVALID_ARGUMENT",
            "message": "Invalid value in 'secret user message'",
        }
    }

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(400, body))

    assert "400" in str(error.value)
    assert "INVALID_ARGUMENT" in str(error.value)
    assert "secret user message" not in str(error.value)


def test_error_response_message_drops_a_status_that_is_not_a_code() -> None:
    body = {"error": {"code": 400, "status": "secret user message, not a status code"}}

    with pytest.raises(LLMUnavailableError) as error:
        generate(respond(400, body))

    assert "400" in str(error.value)
    assert "secret user message" not in str(error.value)
