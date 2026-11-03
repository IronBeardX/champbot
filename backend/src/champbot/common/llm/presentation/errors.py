import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot.common.core.presentation.errors import error_response
from champbot.common.llm.domain.provider import LLMError, LLMRateLimitError, LLMTimeoutError

logger = logging.getLogger(__name__)


def register_llm_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, _handle_llm_error)


async def _handle_llm_error(_: Request, error: Exception) -> JSONResponse:
    logger.warning("LLM request failed: %r", error)
    match error:
        case LLMTimeoutError():
            return error_response(
                HTTPStatus.GATEWAY_TIMEOUT,
                "The assistant took too long to answer. Please try again.",
            )
        case LLMRateLimitError(retry_after_seconds=seconds):
            headers = None if seconds is None else {"Retry-After": str(seconds)}
            return error_response(
                HTTPStatus.TOO_MANY_REQUESTS,
                "The assistant is busy. Please try again later.",
                headers=headers,
            )
        case _:
            return error_response(
                HTTPStatus.BAD_GATEWAY, "The assistant is unavailable. Please try again later."
            )
