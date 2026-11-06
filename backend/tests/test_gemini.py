import asyncio
import json
import logging
import time
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

TEST_GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

FALLBACK_MODEL = "fallback-model"


def generate(
    handler: Handler,
    messages: Sequence[Message] = HELLO_CONVERSATION,
    system_instruction: str | None = None,
    *,
    response_schema: Mapping[str, Any] | None = None,
    thinking_level: str | None = None,
    fallback_model: str | None = None,
    retry_delay: Callable[[], float] = lambda: 0.0,
    min_retry_seconds: float = 8.0,
    timeout_seconds: float = 25.0,
) -> str:
    provider = GeminiProvider(
        "test-key",
        "test-model",
        TEST_GENERATE_CONTENT_URL,
        transport=httpx.MockTransport(handler),
        timeout_seconds=timeout_seconds,
        thinking_level=thinking_level,
        fallback_model=fallback_model,
        retry_delay=retry_delay,
        min_retry_seconds=min_retry_seconds,
    )
    return asyncio.run(
        provider.generate(list(messages), system_instruction, response_schema=response_schema)
    )


def answer_with_parts(*parts: dict[str, Any]) -> Handler:
    body = {
        "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": list(parts)}}]
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


def sequenced(*steps: Handler) -> Handler:
    remaining = list(steps)

    def handler(request: httpx.Request) -> httpx.Response:
        return remaining.pop(0)(request)

    return handler


def capturing(handler: Handler, requests: list[httpx.Request]) -> Handler:
    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return wrapped


def counting_retry_delay(value: float = 0.0) -> tuple[Callable[[], float], list[None]]:
    calls: list[None] = []

    def retry_delay() -> float:
        calls.append(None)
        return value

    return retry_delay, calls


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
        "test-key",
        "test-model",
        TEST_GENERATE_CONTENT_URL,
        transport=httpx.MockTransport(slow_response),
        timeout_seconds=0.05,
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


@pytest.mark.parametrize(
    "first_failure",
    [
        pytest.param(respond(503, {"error": {"status": "UNAVAILABLE"}}), id="503"),
        pytest.param(respond(500, {"error": {"status": "INTERNAL"}}), id="500"),
        pytest.param(raise_error(httpx.ConnectError("refused")), id="connect-error"),
    ],
)
def test_retries_same_model_after_jitter_when_no_fallback_is_configured(
    first_failure: Handler,
) -> None:
    requests: list[httpx.Request] = []
    retry_delay, calls = counting_retry_delay()

    answer = generate(
        capturing(sequenced(first_failure, answer_with_parts({"text": "Hi"})), requests),
        retry_delay=retry_delay,
    )

    assert answer == "Hi"
    assert len(requests) == 2
    assert all(request.url.path.endswith("/test-model:generateContent") for request in requests)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "first_failure",
    [
        pytest.param(respond(503, {"error": {"status": "UNAVAILABLE"}}), id="503"),
        pytest.param(respond(500, {"error": {"status": "INTERNAL"}}), id="500"),
        pytest.param(raise_error(httpx.ConnectError("refused")), id="connect-error"),
    ],
)
def test_retries_fallback_model_with_identical_body_when_configured(
    first_failure: Handler,
) -> None:
    requests: list[httpx.Request] = []
    retry_delay, calls = counting_retry_delay()

    answer = generate(
        capturing(sequenced(first_failure, answer_with_parts({"text": "Hi"})), requests),
        fallback_model=FALLBACK_MODEL,
        retry_delay=retry_delay,
    )

    assert answer == "Hi"
    assert len(requests) == 2
    assert requests[0].url.path.endswith("/test-model:generateContent")
    assert requests[1].url.path.endswith(f"/{FALLBACK_MODEL}:generateContent")
    assert requests[0].content == requests[1].content
    assert calls == []


def test_falls_back_on_model_not_found() -> None:
    answer = generate(
        sequenced(
            respond(404, {"error": {"status": "NOT_FOUND"}}), answer_with_parts({"text": "Hi"})
        ),
        fallback_model=FALLBACK_MODEL,
    )

    assert answer == "Hi"


def test_model_not_found_surfaces_without_a_fallback() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError) as error:
        generate(capturing(respond(404, {"error": {"status": "NOT_FOUND"}}), requests))

    assert len(requests) == 1
    assert "404" in str(error.value)


def test_falls_back_on_rate_limit() -> None:
    answer = generate(
        sequenced(rate_limited("5s"), answer_with_parts({"text": "Hi"})),
        fallback_model=FALLBACK_MODEL,
    )

    assert answer == "Hi"


def test_rate_limit_surfaces_without_a_fallback() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMRateLimitError) as error:
        generate(capturing(rate_limited("5s"), requests))

    assert len(requests) == 1
    assert error.value.retry_after_seconds == 5


@pytest.mark.parametrize(
    "fallback_model", [None, FALLBACK_MODEL], ids=["no-fallback", "with-fallback"]
)
def test_client_error_is_never_retried(fallback_model: str | None) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(respond(400, {"error": {"status": "INVALID_ARGUMENT"}}), requests),
            fallback_model=fallback_model,
        )

    assert len(requests) == 1


def test_blocked_answer_is_never_retried_even_with_a_fallback() -> None:
    requests: list[httpx.Request] = []
    body = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": [{"text": "x"}]}}]}

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(respond(200, body), requests),
            response_schema=SAMPLE_SCHEMA,
            fallback_model=FALLBACK_MODEL,
        )

    assert len(requests) == 1


def test_empty_answer_is_never_retried_even_with_a_fallback() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(answer_with_parts({"text": "thinking", "thought": True}), requests),
            fallback_model=FALLBACK_MODEL,
        )

    assert len(requests) == 1


def test_read_timeout_is_never_retried_even_with_a_fallback() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMTimeoutError):
        generate(
            capturing(raise_error(httpx.ReadTimeout("timed out")), requests),
            fallback_model=FALLBACK_MODEL,
        )

    assert len(requests) == 1


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ReadError("broken"), id="read-error"),
        pytest.param(httpx.InvalidURL("bad model id"), id="invalid-url"),
    ],
)
def test_other_transport_errors_are_never_retried_even_with_a_fallback(error: Exception) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(capturing(raise_error(error), requests), fallback_model=FALLBACK_MODEL)

    assert len(requests) == 1


def test_second_failure_always_surfaces_with_no_further_retry() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(
                sequenced(
                    respond(503, {"error": {"status": "UNAVAILABLE"}}),
                    respond(503, {"error": {"status": "UNAVAILABLE"}}),
                ),
                requests,
            ),
            fallback_model=FALLBACK_MODEL,
        )

    assert len(requests) == 2


def test_last_attempts_error_type_wins_over_the_first() -> None:
    with pytest.raises(LLMRateLimitError) as error:
        generate(
            sequenced(respond(503, {"error": {"status": "UNAVAILABLE"}}), rate_limited("9s")),
            fallback_model=FALLBACK_MODEL,
        )

    assert error.value.retry_after_seconds == 9


def test_second_attempt_gets_only_the_time_left_on_the_shared_deadline() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(0.05)
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})

    provider = GeminiProvider(
        "test-key",
        "test-model",
        TEST_GENERATE_CONTENT_URL,
        transport=httpx.MockTransport(handler),
        timeout_seconds=0.08,
        retry_delay=lambda: 0.0,
        min_retry_seconds=0.0,
    )

    started = time.monotonic()
    answer = asyncio.run(provider.generate(list(HELLO_CONVERSATION)))
    elapsed = time.monotonic() - started

    assert answer == "Hi"
    assert calls == 2
    assert elapsed < 0.08 + 0.05


def test_retry_skipped_when_jitter_would_leave_too_little_budget() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(respond(503, {"error": {"status": "UNAVAILABLE"}}), requests),
            retry_delay=lambda: 100.0,
            min_retry_seconds=8.0,
            timeout_seconds=25.0,
        )

    assert len(requests) == 1


def test_fallback_equal_to_primary_model_is_treated_as_no_fallback() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMUnavailableError):
        generate(
            capturing(respond(404, {"error": {"status": "NOT_FOUND"}}), requests),
            fallback_model="test-model",
        )

    assert len(requests) == 1


def test_logs_attempt_number_model_and_scrubbed_error_without_body_or_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    body = {"error": {"code": 503, "status": "UNAVAILABLE", "message": "secret user message"}}

    generate(
        sequenced(respond(503, body), answer_with_parts({"text": "Hi"})),
        fallback_model=FALLBACK_MODEL,
    )

    [record] = caplog.records
    message = record.getMessage()
    assert "attempt 1" in message
    assert "test-model" in message
    assert "503" in message
    assert "UNAVAILABLE" in message
    assert FALLBACK_MODEL in message
    assert "secret user message" not in message
    assert "test-key" not in message
