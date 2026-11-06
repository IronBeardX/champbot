from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import Request

from champbot.chat.answer.application.flight_results import today_in_ist
from champbot.chat.answer.infrastructure.settings import load_retrieval_settings
from champbot.common.core.infrastructure.cloudflare import load_cloudflare_settings
from champbot.common.core.infrastructure.http_client import open_http_client
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.embeddings.infrastructure.workers_ai import WorkersAIEmbedder
from champbot.common.llm.domain.provider import LLMProvider, ProviderEnum
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.common.llm.infrastructure.groq import GroqProvider
from champbot.common.llm.infrastructure.settings import (
    load_gemini_settings,
    load_groq_settings,
    load_llm_provider,
)
from champbot.common.vector_store.domain.store import VectorStore
from champbot.common.vector_store.infrastructure.vectorize import VectorizeStore

_RUNTIME_TOKEN_SETTING = "CF_RUNTIME_API_TOKEN"
POLICY_INDEX_NAME = "champbot-policies"
_RETRIEVAL_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class RetrievalPorts:
    embedder: Embedder
    vector_store: VectorStore


def get_llm_provider(request: Request) -> LLMProvider:
    env = request.scope.get("env")
    match load_llm_provider(env):
        case ProviderEnum.GEMINI:
            settings = load_gemini_settings(env)
            return GeminiProvider(
                settings.api_key,
                settings.model,
                settings.generate_content_url,
                thinking_level=settings.thinking_level,
                fallback_model=settings.fallback_model,
            )
        case ProviderEnum.GROQ:
            settings = load_groq_settings(env)
            return GroqProvider(
                settings.api_key,
                settings.model,
                settings.generate_content_url,
                thinking_level=settings.thinking_level,
            )


@asynccontextmanager
async def open_retrieval_ports(workers_env: object | None = None) -> AsyncGenerator[RetrievalPorts]:
    settings = load_cloudflare_settings(_RUNTIME_TOKEN_SETTING, workers_env)
    # TEMP(IRO-164): one httpx client per use, shared by both adapters.
    # IRO-164 replaces this with a client reused across requests (decision 20).
    async with open_http_client() as client:
        yield RetrievalPorts(
            embedder=WorkersAIEmbedder(
                client,
                settings.account_id,
                settings.api_token,
                timeout_seconds=_RETRIEVAL_TIMEOUT_SECONDS,
            ),
            vector_store=VectorizeStore(
                client,
                settings.account_id,
                settings.api_token,
                POLICY_INDEX_NAME,
                timeout_seconds=_RETRIEVAL_TIMEOUT_SECONDS,
            ),
        )


async def get_retrieval_ports(request: Request) -> AsyncGenerator[RetrievalPorts]:
    async with open_retrieval_ports(request.scope.get("env")) as ports:
        yield ports


def get_min_score(request: Request) -> float:
    return load_retrieval_settings(request.scope.get("env")).min_score


def get_today() -> date:
    return today_in_ist(datetime.now(UTC))
