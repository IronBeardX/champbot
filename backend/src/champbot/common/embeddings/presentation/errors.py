import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot.common.core.presentation.errors import error_response
from champbot.common.embeddings.domain.embedder import EmbeddingError, EmbeddingTimeoutError

logger = logging.getLogger(__name__)


def register_embedding_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(EmbeddingError, _handle_embedding_error)


async def _handle_embedding_error(_: Request, error: Exception) -> JSONResponse:
    logger.warning("Embedding request failed: %r", error)
    match error:
        case EmbeddingTimeoutError():
            return error_response(
                HTTPStatus.GATEWAY_TIMEOUT,
                "The assistant took too long to answer. Please try again.",
            )
        case _:
            return error_response(
                HTTPStatus.BAD_GATEWAY, "The assistant is unavailable. Please try again later."
            )
