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

_STOP_FINISH_REASON = "stop"
_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)s")


class GroqProvider:
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
        body = _build_request_body(
            self._model,
            messages,
            system_instruction,
            response_schema,
            self._thinking_level,
        )

        response = await self._post_chat_completion(body)

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise LLMRateLimitError(_parse_retry_delay_seconds(response))

        if response.is_error:
            raise LLMUnavailableError(
                f"Groq returned HTTP {response.status_code} ({_describe_error_status(response)})"
            )

        if response_schema is not None:
            _check_finish_reason(response)

        return _extract_answer(response)

    async def _post_chat_completion(
        self,
        body: dict[str, Any],
    ) -> httpx.Response:
        # httpx timeouts apply to each phase; asyncio.timeout bounds
        # the complete request, including connection establishment.
        try:
            async with (
                asyncio.timeout(self._timeout_seconds),
                httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client,
            ):
                return await client.post(
                    self._generate_content_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )

        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("Groq did not answer in time") from error

        except httpx.HTTPError as error:
            raise LLMUnavailableError(f"Could not reach Groq: {error!r}") from error


def _build_request_body(
    model: str,
    messages: list[Message],
    system_instruction: str | None,
    response_schema: Mapping[str, Any] | None,
    thinking_level: str | None,
) -> dict[str, Any]:
    request_messages: list[dict[str, str]] = []

    if system_instruction is not None and system_instruction.strip():
        request_messages.append({"role": "system", "content": system_instruction})

    request_messages.extend(
        {
            "role": _groq_role(message.role),
            "content": message.text,
        }
        for message in messages
    )

    body: dict[str, Any] = {
        "model": model,
        "messages": request_messages,
    }

    body.update(_build_generation_config(response_schema, thinking_level))

    return body


def _build_generation_config(
    response_schema: Mapping[str, Any] | None,
    thinking_level: str | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {}

    if thinking_level is not None:
        config["reasoning_effort"] = thinking_level

    if response_schema is not None:
        config["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "schema": dict(response_schema),
                "strict": False,
            },
        }

    return config


def _groq_role(role: Role) -> str:
    match role:
        case Role.USER:
            return "user"
        case Role.ASSISTANT:
            return "assistant"
        case _:
            raise ValueError(f"Unsupported message role: {role!r}")


def _check_finish_reason(response: httpx.Response) -> None:
    # Structured responses must not be truncated or interrupted.
    try:
        finish_reason: Any = response.json()["choices"][0].get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError):
        finish_reason = None

    if finish_reason != _STOP_FINISH_REASON:
        raise LLMUnavailableError(
            f"Groq returned an incomplete structured answer ({_describe_missing_answer(response)})"
        )


def _extract_answer(response: httpx.Response) -> str:
    try:
        answer: Any = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        answer = None

    if not isinstance(answer, str) or not answer.strip():
        raise LLMUnavailableError(f"Groq returned no answer ({_describe_missing_answer(response)})")

    return answer


def _describe_missing_answer(response: httpx.Response) -> str:
    # Only reports API metadata. Never expose generated content in logs.
    try:
        payload: Any = response.json()
        choices: list[Any] = payload.get("choices") or [{}]
        finish_reason: Any = choices[0].get("finish_reason")
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        return "unparseable body"

    return f"finish_reason={_as_code(finish_reason)}"


def _describe_error_status(response: httpx.Response) -> str:
    # Error messages may contain request data. Only retain the error code.
    try:
        error: Any = response.json()["error"]
        code: Any = error.get("code") or error.get("type")
    except (ValueError, KeyError, TypeError, AttributeError):
        return "no code"

    return _as_code(code)


def _as_code(value: object) -> str:
    if value is None:
        return "none"

    if isinstance(value, str) and _CODE_PATTERN.fullmatch(value):
        return value

    return "unknown"


def _parse_retry_delay_seconds(
    response: httpx.Response,
) -> int | None:
    # Groq communicates retry delays through the Retry-After header.
    retry_after = response.headers.get("retry-after")

    if retry_after is None:
        return None

    try:
        seconds = math.ceil(float(retry_after))
    except (ValueError, OverflowError):
        match = _DURATION_PATTERN.fullmatch(retry_after.strip())

        if not match:
            return None

        try:
            seconds = math.ceil(float(match.group(1)))
        except OverflowError:
            return _MAX_RETRY_AFTER_SECONDS

    return min(max(seconds, 0), _MAX_RETRY_AFTER_SECONDS)
