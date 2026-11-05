from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Request

from champbot.chat.answer.infrastructure.settings import load_retrieval_settings
from champbot.common.core.infrastructure.cloudflare import load_cloudflare_settings
from champbot.common.core.infrastructure.http_client import open_http_client
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.embeddings.infrastructure.workers_ai import WorkersAIEmbedder
from champbot.common.llm.domain.provider import LLMProvider
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.common.llm.infrastructure.settings import load_gemini_settings
from champbot.common.vector_store.domain.store import VectorStore
from champbot.common.vector_store.infrastructure.vectorize import VectorizeStore

_RUNTIME_TOKEN_SETTING = "CF_RUNTIME_API_TOKEN"
_POLICY_INDEX_NAME = "champbot-policies"
_RETRIEVAL_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class RetrievalPorts:
    embedder: Embedder
    vector_store: VectorStore


def get_llm_provider(request: Request) -> LLMProvider:
    settings = load_gemini_settings(request.scope.get("env"))
    return GeminiProvider(settings.api_key, settings.model)


async def get_retrieval_ports(request: Request) -> AsyncGenerator[RetrievalPorts]:
    settings = load_cloudflare_settings(_RUNTIME_TOKEN_SETTING, request.scope.get("env"))
    # TEMP(IRO-164): one httpx client per request, shared by both adapters.
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
                _POLICY_INDEX_NAME,
                timeout_seconds=_RETRIEVAL_TIMEOUT_SECONDS,
            ),
        )


def get_min_score(request: Request) -> float:
    return load_retrieval_settings(request.scope.get("env")).min_score
