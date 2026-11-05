import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot.common.core.presentation.errors import error_response
from champbot.common.vector_store.domain.store import VectorStoreError, VectorStoreTimeoutError

logger = logging.getLogger(__name__)


def register_vector_store_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(VectorStoreError, _handle_vector_store_error)


async def _handle_vector_store_error(_: Request, error: Exception) -> JSONResponse:
    logger.warning("Vector store request failed: %r", error)
    match error:
        case VectorStoreTimeoutError():
            return error_response(
                HTTPStatus.GATEWAY_TIMEOUT,
                "The assistant took too long to answer. Please try again.",
            )
        case _:
            return error_response(
                HTTPStatus.BAD_GATEWAY, "The assistant is unavailable. Please try again later."
            )
