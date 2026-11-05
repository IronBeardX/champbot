import asyncio
import json
from typing import Any

import httpx

from champbot.common.core.infrastructure.cloudflare import (
    CLOUDFLARE_API_BASE,
    describe_cloudflare_errors,
)
from champbot.common.vector_store.domain.store import (
    Chunk,
    ScoredChunk,
    VectorStoreError,
    VectorStoreTimeoutError,
)

_MAX_VECTORS_PER_REQUEST = 1000
_REQUEST_TIMEOUT_SECONDS = 60.0


class VectorizeStore:
    def __init__(
        self,
        client: httpx.AsyncClient,
        account_id: str,
        api_token: str,
        index_name: str,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._api_token = api_token
        self._index_name = index_name
        self._timeout_seconds = timeout_seconds

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        mutation_ids: list[str] = []
        for batch in _batches(chunks, _MAX_VECTORS_PER_REQUEST):
            mutation_ids.append(await self._upsert_batch(batch))
        return mutation_ids

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        response = await self._post(
            "query",
            content=json.dumps(
                {"vector": vector, "topK": top_k, "returnValues": False, "returnMetadata": "all"}
            ),
            content_type="application/json",
        )
        if response.is_error:
            raise VectorStoreError(
                f"Vectorize returned HTTP {response.status_code} "
                f"({describe_cloudflare_errors(response)})"
            )
        return _extract_matches(response)

    async def _upsert_batch(self, batch: list[Chunk]) -> str:
        response = await self._post(
            "upsert", content=_to_ndjson(batch), content_type="application/x-ndjson"
        )
        if response.is_error:
            raise VectorStoreError(
                f"Vectorize returned HTTP {response.status_code} "
                f"({describe_cloudflare_errors(response)})"
            )
        return _extract_mutation_id(response)

    async def _post(self, action: str, *, content: str, content_type: str) -> httpx.Response:
        url = (
            f"{CLOUDFLARE_API_BASE}/accounts/{self._account_id}"
            f"/vectorize/v2/indexes/{self._index_name}/{action}"
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_token}",
                        "Content-Type": content_type,
                    },
                    content=content,
                    timeout=self._timeout_seconds,
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise VectorStoreTimeoutError("Vectorize did not answer in time") from error
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise VectorStoreError(f"Could not reach Vectorize: {error!r}") from error


def _batches(chunks: list[Chunk], size: int) -> list[list[Chunk]]:
    return [chunks[index : index + size] for index in range(0, len(chunks), size)]


def _to_ndjson(chunks: list[Chunk]) -> str:
    lines = (
        json.dumps({"id": chunk.id, "values": chunk.vector, "metadata": chunk.metadata})
        for chunk in chunks
    )
    return "\n".join(lines)


def _extract_mutation_id(response: httpx.Response) -> str:
    try:
        mutation_id = response.json()["result"]["mutationId"]
    except (ValueError, KeyError, TypeError) as error:
        raise VectorStoreError("Vectorize returned an unparseable response") from error
    if not isinstance(mutation_id, str) or not mutation_id:
        raise VectorStoreError("Vectorize returned no mutation id")
    return mutation_id


def _extract_matches(response: httpx.Response) -> list[ScoredChunk]:
    try:
        matches: list[Any] = response.json()["result"]["matches"]
    except (ValueError, KeyError, TypeError) as error:
        raise VectorStoreError("Vectorize returned an unparseable response") from error

    scored_chunks: list[ScoredChunk] = []
    for match in matches:
        try:
            metadata = {
                key: value for key, value in match["metadata"].items() if isinstance(value, str)
            }
            scored_chunks.append(
                ScoredChunk(id=match["id"], score=float(match["score"]), metadata=metadata)
            )
        except (KeyError, TypeError, ValueError) as error:
            raise VectorStoreError("Vectorize returned an unparseable match") from error
    return scored_chunks
