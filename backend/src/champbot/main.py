import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from champbot.chat.answer.presentation import rest_api as chat_answer_api
from champbot.common.core.presentation import rest_api as core_api
from champbot.common.core.presentation.errors import register_core_error_handlers
from champbot.common.embeddings.presentation.errors import register_embedding_error_handlers
from champbot.common.flights.presentation import rest_api as flights_api
from champbot.common.llm.presentation.errors import register_llm_error_handlers
from champbot.common.vector_store.presentation.errors import register_vector_store_error_handlers

logging.basicConfig(level=logging.INFO)

# Deploy topology, not a secret: create_app() runs at import time, before any
# Workers env binding exists, so the frontend's origin can't come from a
# per-request setting lookup.
FRONTEND_ORIGIN_REGEX = r"https://champbot-frontend\.alejandroyeroval\.workers\.dev|http://(localhost|127\.0\.0\.1)(:\d+)?"


def create_app() -> FastAPI:
    app = FastAPI(title="ChampBot")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=FRONTEND_ORIGIN_REGEX,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
    )
    app.include_router(core_api.router)
    app.include_router(chat_answer_api.router)
    app.include_router(flights_api.router)
    register_core_error_handlers(app)
    register_llm_error_handlers(app)
    register_embedding_error_handlers(app)
    register_vector_store_error_handlers(app)
    return app


app = create_app()
