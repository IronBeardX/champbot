import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from champbot.common.core.domain.exceptions import MissingSettingError

logger = logging.getLogger(__name__)


def register_core_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MissingSettingError, _handle_missing_setting)


async def _handle_missing_setting(_: Request, error: Exception) -> JSONResponse:
    logger.error("Configuration error: %s", error)
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR, "The assistant is not available right now."
    )


def error_response(
    status_code: int, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
