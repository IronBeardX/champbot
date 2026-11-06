import asyncio
import math
import re
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import httpx

from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

_REQUEST_TIMEOUT_SECONDS = 25.0
_MAX_RETRY_AFTER_SECONDS = 3600
_RETRY_INFO_TYPE = "type.googleapis.com/google.rpc.RetryInfo"
_STOP_FINISH_REASON = "STOP"
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)s")
_CODE_PATTERN = re.compile(r"[A-Z_]{1,40}")


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        generate_content_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
        thinking_level: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._generate_content_url = generate_content_url
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._thinking_level = thinking_level

    async def generate(
        self,
        messages: list[Message],
        system_instruction: str | None = None,
        *,
        response_schema: Mapping[str, Any] | None = None,
    ) -> str:
        response = await self._post_generate_content(
            _build_request_body(messages, system_instruction, response_schema, self._thinking_level)
        )
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise LLMRateLimitError(_parse_retry_delay_seconds(response))
        if response.is_error:
            raise LLMUnavailableError(
                f"Gemini returned HTTP {response.status_code} ({_describe_error_status(response)})"
            )
        if response_schema is not None:
            _check_finish_reason(response)
        return _extract_answer(response)

    async def _post_generate_content(self, body: dict[str, Any]) -> httpx.Response:
        # httpx timeouts apply to each phase; asyncio.timeout bounds the whole request.
        try:
            async with (
                asyncio.timeout(self._timeout_seconds),
                httpx.AsyncClient(
                    timeout=self._timeout_seconds, transport=self._transport
                ) as client,
            ):
                return await client.post(
                    self._generate_content_url.format(model=self._model),
                    headers={"x-goog-api-key": self._api_key},
                    json=body,
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("Gemini did not answer in time") from error
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise LLMUnavailableError(f"Could not reach Gemini: {error!r}") from error


def _build_request_body(
    messages: list[Message],
    system_instruction: str | None,
    response_schema: Mapping[str, Any] | None,
    thinking_level: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contents": [
            {"role": _gemini_role(message.role), "parts": [{"text": message.text}]}
            for message in messages
        ]
    }
    if system_instruction is not None and system_instruction.strip():
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    generation_config = _build_generation_config(response_schema, thinking_level)
    if generation_config:
        body["generationConfig"] = generation_config
    return body


def _build_generation_config(
    response_schema: Mapping[str, Any] | None, thinking_level: str | None
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {}
    if thinking_level is not None:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    if response_schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseJsonSchema"] = dict(response_schema)
    return generation_config


def _gemini_role(role: Role) -> str:
    match role:
        case Role.USER:
            return "user"
        case Role.ASSISTANT:
            return "model"


def _check_finish_reason(response: httpx.Response) -> None:
    # A structured answer can't be trusted truncated or filtered: only STOP is usable.
    try:
        finish_reason: Any = response.json()["candidates"][0].get("finishReason")
    except (ValueError, KeyError, IndexError, TypeError):
        finish_reason = None
    if finish_reason != _STOP_FINISH_REASON:
        raise LLMUnavailableError(
            "Gemini returned an incomplete structured answer "
            f"({_describe_missing_answer(response)})"
        )


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
