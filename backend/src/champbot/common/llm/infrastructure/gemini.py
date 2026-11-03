import asyncio
import math
import re
from http import HTTPStatus
from typing import Any

import httpx

from champbot.common.llm.domain.provider import (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

_GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_REQUEST_TIMEOUT_SECONDS = 25.0
_MAX_RETRY_AFTER_SECONDS = 3600
_RETRY_INFO_TYPE = "type.googleapis.com/google.rpc.RetryInfo"
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)s")
_CODE_PATTERN = re.compile(r"[A-Z_]{1,40}")


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def generate(self, prompt: str) -> str:
        response = await self._post_generate_content(prompt)
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise LLMRateLimitError(_parse_retry_delay_seconds(response))
        if response.is_error:
            raise LLMUnavailableError(
                f"Gemini returned HTTP {response.status_code} ({_describe_error_status(response)})"
            )
        return _extract_answer(response)

    async def _post_generate_content(self, prompt: str) -> httpx.Response:
        # httpx timeouts apply to each phase; asyncio.timeout bounds the whole request.
        try:
            async with (
                asyncio.timeout(self._timeout_seconds),
                httpx.AsyncClient(
                    timeout=self._timeout_seconds, transport=self._transport
                ) as client,
            ):
                return await client.post(
                    _GENERATE_CONTENT_URL.format(model=self._model),
                    headers={"x-goog-api-key": self._api_key},
                    json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("Gemini did not answer in time") from error
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise LLMUnavailableError(f"Could not reach Gemini: {error!r}") from error


def _extract_answer(response: httpx.Response) -> str:
    # Thinking models return their reasoning as extra parts flagged with "thought".
    try:
        parts: list[Any] = response.json()["candidates"][0]["content"]["parts"]
        answer = "".join(
            part["text"] for part in parts if "text" in part and not part.get("thought")
        )
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        answer = ""
    if not answer.strip():
        raise LLMUnavailableError(
            f"Gemini returned no answer ({_describe_missing_answer(response)})"
        )
    return answer


def _describe_missing_answer(response: httpx.Response) -> str:
    # Reports Gemini's reason codes only, so model text never ends up in the logs.
    try:
        payload: Any = response.json()
        candidates: list[Any] = payload.get("candidates") or [{}]
        feedback: dict[str, Any] = payload.get("promptFeedback") or {}
        finish_reason: Any = candidates[0].get("finishReason")
        block_reason: Any = feedback.get("blockReason")
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        return "unparseable body"
    return f"finishReason={_as_code(finish_reason)}, blockReason={_as_code(block_reason)}"


def _describe_error_status(response: httpx.Response) -> str:
    # Error bodies can quote the request, so only Gemini's status code is kept for the logs.
    try:
        status: Any = response.json()["error"]["status"]
    except (ValueError, KeyError, TypeError):
        return "no status"
    return _as_code(status)


def _as_code(value: object) -> str:
    if value is None:
        return "none"
    return value if isinstance(value, str) and _CODE_PATTERN.fullmatch(value) else "odd code"


def _parse_retry_delay_seconds(response: httpx.Response) -> int | None:
    try:
        details: list[Any] = response.json()["error"]["details"]
        retry_delay = next(
            detail["retryDelay"] for detail in details if detail.get("@type") == _RETRY_INFO_TYPE
        )
    except (ValueError, KeyError, TypeError, AttributeError, StopIteration):
        return None
    match = _DURATION_PATTERN.fullmatch(str(retry_delay))
    if not match:
        return None
    try:
        seconds = math.ceil(float(match.group(1)))
    except OverflowError:
        return _MAX_RETRY_AFTER_SECONDS
    return min(seconds, _MAX_RETRY_AFTER_SECONDS)
