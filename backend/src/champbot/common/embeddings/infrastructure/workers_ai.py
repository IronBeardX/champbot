import asyncio
from typing import Any

import httpx

from champbot.common.core.infrastructure.cloudflare import (
    CLOUDFLARE_API_BASE,
    describe_cloudflare_errors,
)
from champbot.common.embeddings.domain.embedder import EmbeddingError

_MODEL = "@cf/baai/bge-m3"
_MAX_TEXTS_PER_REQUEST = 50
_REQUEST_TIMEOUT_SECONDS = 60.0


class WorkersAIEmbedder:
    def __init__(
        self,
        client: httpx.AsyncClient,
        account_id: str,
        api_token: str,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._api_token = api_token
        self._timeout_seconds = timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, _MAX_TEXTS_PER_REQUEST):
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = await self._post_run(batch)
        if response.is_error:
            raise EmbeddingError(
                f"Workers AI returned HTTP {response.status_code} "
                f"({describe_cloudflare_errors(response)})"
            )
        return _extract_vectors(response, len(batch))

    async def _post_run(self, batch: list[str]) -> httpx.Response:
        url = f"{CLOUDFLARE_API_BASE}/accounts/{self._account_id}/ai/run/{_MODEL}"
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_token}"},
                    json={"text": batch},
                    timeout=self._timeout_seconds,
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise EmbeddingError("Workers AI did not answer in time") from error
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise EmbeddingError(f"Could not reach Workers AI: {error!r}") from error


def _batches(texts: list[str], size: int) -> list[list[str]]:
    return [texts[index : index + size] for index in range(0, len(texts), size)]


def _extract_vectors(response: httpx.Response, expected_count: int) -> list[list[float]]:
    try:
        vectors: list[Any] = response.json()["result"]["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise EmbeddingError("Workers AI returned an unparseable response") from error
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"Workers AI returned {len(vectors)} vectors for {expected_count} texts"
        )
    return vectors
