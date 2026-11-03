import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot import chat
from champbot.config import MissingSettingError
from champbot.llm import LLMError, LLMRateLimitError, LLMTimeoutError

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="ChampBot")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(chat.router)
    app.add_exception_handler(LLMError, handle_llm_error)
    app.add_exception_handler(MissingSettingError, handle_missing_setting)
    return app


async def handle_llm_error(_: Request, error: Exception) -> JSONResponse:
    logger.warning("LLM request failed: %r", error)
    match error:
        case LLMTimeoutError():
            return _error_response(
                HTTPStatus.GATEWAY_TIMEOUT,
                "The assistant took too long to answer. Please try again.",
            )
        case LLMRateLimitError(retry_after_seconds=seconds):
            headers = None if seconds is None else {"Retry-After": str(seconds)}
            return _error_response(
                HTTPStatus.TOO_MANY_REQUESTS,
                "The assistant is busy. Please try again later.",
                headers=headers,
            )
        case _:
            return _error_response(
                HTTPStatus.BAD_GATEWAY, "The assistant is unavailable. Please try again later."
            )


async def handle_missing_setting(_: Request, error: Exception) -> JSONResponse:
    logger.error("Configuration error: %s", error)
    return _error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR, "The assistant is not available right now."
    )


def _error_response(
    status_code: int, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code, headers=headers)


app = create_app()
