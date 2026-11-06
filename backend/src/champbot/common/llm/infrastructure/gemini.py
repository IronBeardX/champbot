import asyncio
import logging
import math
import random
import re
from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Any

import httpx

from champbot.common.llm.domain.message import Message, Role
from champbot.common.llm.domain.provider import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 25.0
_MIN_RETRY_SECONDS = 8.0
_JITTER_MIN_SECONDS = 0.5
_JITTER_MAX_SECONDS = 1.5
_MAX_RETRY_AFTER_SECONDS = 3600
_RETRY_INFO_TYPE = "type.googleapis.com/google.rpc.RetryInfo"
_STOP_FINISH_REASON = "STOP"
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)s")
_CODE_PATTERN = re.compile(r"[A-Z_]{1,40}")
_FALLBACK_STATUSES = frozenset({HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.SERVICE_UNAVAILABLE})


def _default_retry_delay() -> float:
    return random.uniform(_JITTER_MIN_SECONDS, _JITTER_MAX_SECONDS)


class _GeminiStatusError(LLMUnavailableError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class _GeminiConnectError(LLMUnavailableError):
    pass


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        generate_content_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
        thinking_level: str | None = None,
        fallback_model: str | None = None,
        retry_delay: Callable[[], float] = _default_retry_delay,
        min_retry_seconds: float = _MIN_RETRY_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._generate_content_url = generate_content_url
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._thinking_level = thinking_level
        self._fallback_model = fallback_model if fallback_model != model else None
        self._retry_delay = retry_delay
        self._min_retry_seconds = min_retry_seconds

    async def generate(
        self,
        messages: list[Message],
        system_instruction: str | None = None,
        *,
        response_schema: Mapping[str, Any] | None = None,
    ) -> str:
        body = _build_request_body(
            messages, system_instruction, response_schema, self._thinking_level
        )
        model = self._model
        try:
            async with asyncio.timeout(self._timeout_seconds) as timeout_scope:
                for attempt in (1, 2):
                    try:
                        return await self._attempt(
                            model, body, response_schema, _time_left(timeout_scope)
                        )
                    except LLMError as error:
                        target = (
                            _retry_target(error, model, self._fallback_model)
                            if attempt == 1
                            else None
                        )
                        delay = self._retry_delay() if target == model else 0.0
                        if target is not None and (
                            _time_left(timeout_scope) - delay < self._min_retry_seconds
                        ):
                            target = None
                            delay = 0.0
                        _log_attempt_failure(attempt, model, error, target)
                        if target is None:
                            raise
                        if delay:
                            await asyncio.sleep(delay)
                        model = target
        except TimeoutError as error:
            # The shared deadline expired across the whole call (any attempt or jitter
            # sleep); the retry loop above never sees this, by construction.
            raise LLMTimeoutError("Gemini did not answer in time") from error
        raise AssertionError("unreachable: asyncio.timeout always raises on expiry")

    async def _attempt(
        self,
        model: str,
        body: dict[str, Any],
        response_schema: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> str:
        response = await self._post_generate_content(model, body, timeout_seconds)
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise LLMRateLimitError(_parse_retry_delay_seconds(response))
        if response.is_error:
            raise _GeminiStatusError(
                response.status_code,
                f"Gemini returned HTTP {response.status_code} ({_describe_error_status(response)})",
            )
        if response_schema is not None:
            _check_finish_reason(response)
        return _extract_answer(response)

    async def _post_generate_content(
        self, model: str, body: dict[str, Any], timeout_seconds: float
    ) -> httpx.Response:
        # httpx timeouts apply to each phase; the outer asyncio.timeout in generate()
        # bounds the whole call, including any retry and its jitter.
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds, transport=self._transport
            ) as client:
                return await client.post(
                    self._generate_content_url.format(model=model),
                    headers={"x-goog-api-key": self._api_key},
                    json=body,
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("Gemini did not answer in time") from error
        except httpx.ConnectError as error:
            raise _GeminiConnectError(f"Could not connect to Gemini: {error!r}") from error
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise LLMUnavailableError(f"Could not reach Gemini: {error!r}") from error


def _time_left(timeout_scope: asyncio.Timeout) -> float:
    deadline = timeout_scope.when()
    if deadline is None:
        return 0.0
    return deadline - asyncio.get_running_loop().time()


def _retry_target(error: LLMError, model: str, fallback_model: str | None) -> str | None:
    # Per-model Gemini quotas and model retirement mean 429/404 can only be solved by a
    # different model; 503/500/a connect error are retried against the same model too,
    # since the request never reached (or was simply refused by) Gemini.
    if isinstance(error, LLMRateLimitError):
        return fallback_model
    if isinstance(error, _GeminiConnectError):
        return fallback_model or model
    if isinstance(error, _GeminiStatusError):
        if error.status_code == HTTPStatus.NOT_FOUND:
            return fallback_model
        if error.status_code in _FALLBACK_STATUSES:
            return fallback_model or model
    return None


def _describe_next_attempt(target: str | None, model: str) -> str:
    if target is None:
        return "none"
    if target == model:
        return "same model after jitter"
    return target


def _log_attempt_failure(attempt: int, model: str, error: LLMError, target: str | None) -> None:
    logger.warning(
        "Gemini attempt %d on model %s failed (%s); next: %s",
        attempt,
        model,
        error,
        _describe_next_attempt(target, model),
    )


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
