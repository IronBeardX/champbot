from fastapi import FastAPI

from champbot.chat.answer.presentation import rest_api as chat_answer_api
from champbot.common.core.presentation import rest_api as core_api
from champbot.common.core.presentation.errors import register_core_error_handlers
from champbot.common.llm.presentation.errors import register_llm_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="ChampBot")
    app.include_router(core_api.router)
    app.include_router(chat_answer_api.router)
    register_core_error_handlers(app)
    register_llm_error_handlers(app)
    return app


app = create_app()
