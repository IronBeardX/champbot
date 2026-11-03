from fastapi import FastAPI

from champbot import chat
from champbot.common.core.infrastructure.settings import MissingSettingError
from champbot.common.core.presentation.errors import handle_missing_setting
from champbot.common.llm.domain.provider import LLMError
from champbot.common.llm.presentation.errors import handle_llm_error


def create_app() -> FastAPI:
    app = FastAPI(title="ChampBot")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(chat.router)
    app.add_exception_handler(LLMError, handle_llm_error)
    app.add_exception_handler(MissingSettingError, handle_missing_setting)
    return app


app = create_app()
