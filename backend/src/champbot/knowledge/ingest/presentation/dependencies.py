from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from champbot.common.core.infrastructure.cloudflare import load_cloudflare_settings
from champbot.common.core.infrastructure.http_client import open_http_client
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.embeddings.infrastructure.workers_ai import WorkersAIEmbedder
from champbot.common.vector_store.domain.store import VectorStore
from champbot.common.vector_store.infrastructure.vectorize import VectorizeStore

_INGEST_TOKEN_SETTING = "CF_INGEST_API_TOKEN"
_POLICY_INDEX_NAME = "champbot-policies"


@dataclass(frozen=True)
class IngestPorts:
    embedder: Embedder
    vector_store: VectorStore


@asynccontextmanager
async def open_ingest_ports() -> AsyncGenerator[IngestPorts]:
    settings = load_cloudflare_settings(_INGEST_TOKEN_SETTING)
    async with open_http_client() as client:
        yield IngestPorts(
            embedder=WorkersAIEmbedder(client, settings.account_id, settings.api_token),
            vector_store=VectorizeStore(
                client, settings.account_id, settings.api_token, _POLICY_INDEX_NAME
            ),
        )
