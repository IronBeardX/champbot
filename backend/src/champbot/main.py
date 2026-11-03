import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot import chat
from champbot.common.core.infrastructure.settings import MissingSettingError
from champbot.common.core.presentation.errors import error_response, handle_missing_setting
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


app = create_app()
