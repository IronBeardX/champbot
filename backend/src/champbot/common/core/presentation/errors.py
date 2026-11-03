import logging
from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def handle_missing_setting(_: Request, error: Exception) -> JSONResponse:
    logger.error("Configuration error: %s", error)
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR, "The assistant is not available right now."
    )


def error_response(
    status_code: int, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
