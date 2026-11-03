import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from champbot.gemini import GeminiProvider
from champbot.llm import LLMRateLimitError, LLMTimeoutError, LLMUnavailableError

Handler = Callable[[httpx.Request], httpx.Response]


def generate(handler: Handler, prompt: str = "Hello") -> str:
    provider = GeminiProvider("test-key", "test-model", transport=httpx.MockTransport(handler))
    return asyncio.run(provider.generate(prompt))


def answer_with_parts(*parts: dict[str, Any]) -> Handler:
    body = {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}
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


def test_sends_prompt_to_configured_model_with_key_in_header() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer_with_parts({"text": "Hi"})(request)

    generate(handler, prompt="Can I change my flight?")

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "test-key"
    assert json.loads(request.content)["contents"] == [
        {"role": "user", "parts": [{"text": "Can I change my flight?"}]}
    ]


def test_joins_text_parts_and_skips_thoughts() -> None:
    handler = answer_with_parts(
        {"text": "Planning the reply", "thought": True},
        {"text": "Yes, ", "thoughtSignature": "abc"},
        {"text": "you can.", "thought": False},
    )

    assert generate(handler) == "Yes, you can."


@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY"])
def test_answer_text_is_returned_whatever_the_finish_reason(finish_reason: str) -> None:
    body = {
        "candidates": [
            {"finishReason": finish_reason, "content": {"parts": [{"text": "Yes, you"}]}}
        ]
    }

    assert generate(respond(200, body)) == "Yes, you"


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
        asyncio.run(provider.generate("Hello"))


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
