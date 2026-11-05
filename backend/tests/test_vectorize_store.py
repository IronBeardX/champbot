import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from champbot.common.vector_store.domain.store import (
    Chunk,
    ScoredChunk,
    VectorStoreError,
    VectorStoreTimeoutError,
)
from champbot.common.vector_store.infrastructure.vectorize import VectorizeStore

Handler = Callable[[httpx.Request], httpx.Response]


# Shape pinned from a live Vectorize v2 upsert call on 2026-11-05 (one throwaway vector).
def _upsert_response_for(mutation_id: str) -> dict[str, Any]:
    return {
        "result": {"mutationId": mutation_id},
        "result_info": None,
        "success": True,
        "errors": [],
        "messages": [],
    }


# Shape pinned from a live Vectorize v2 query call on 2026-11-05 (champbot-policies, topK=5).
def _query_response_for(matches: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "result": {"count": len(matches), "matches": matches},
        "result_info": None,
        "success": True,
        "errors": [],
        "messages": [],
    }


def make_chunk(suffix: int) -> Chunk:
    return Chunk(
        id=f"chunk-{suffix}",
        vector=[0.1, 0.2, 0.3],
        metadata={"title": "Title", "section": "Section", "text": "Body text"},
    )


def upsert(handler: Handler, chunks: list[Chunk]) -> list[str]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = VectorizeStore(client, "test-account", "test-token", "champbot-policies")
    try:
        return asyncio.run(store.upsert(chunks))
    finally:
        asyncio.run(client.aclose())


def query(handler: Handler, vector: list[float], top_k: int = 5) -> list[ScoredChunk]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = VectorizeStore(client, "test-account", "test-token", "champbot-policies")
    try:
        return asyncio.run(store.query(vector, top_k))
    finally:
        asyncio.run(client.aclose())


def respond(status_code: int, body: Any) -> Handler:
    return lambda _: httpx.Response(status_code, json=body)


def raise_error(error: Exception) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    return handler


def test_posts_ndjson_with_one_line_per_chunk_in_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_upsert_response_for("mutation-1"))

    chunks = [make_chunk(1), make_chunk(2)]
    mutation_ids = upsert(handler, chunks)

    assert mutation_ids == ["mutation-1"]
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["content-type"] == "application/x-ndjson"
    assert request.url.path.endswith("/vectorize/v2/indexes/champbot-policies/upsert")
    assert request.headers["authorization"] == "Bearer test-token"

    lines = request.content.decode().splitlines()
    assert len(lines) == 2
    assert '"id": "chunk-1"' in lines[0]
    assert '"values": [0.1, 0.2, 0.3]' in lines[0]
    assert '"id": "chunk-2"' in lines[1]


def test_more_chunks_than_the_batch_limit_split_into_several_requests() -> None:
    chunks = [make_chunk(i) for i in range(1500)]
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch_sizes.append(len(request.content.decode().splitlines()))
        return httpx.Response(200, json=_upsert_response_for(f"mutation-{len(batch_sizes)}"))

    mutation_ids = upsert(handler, chunks)

    assert batch_sizes == [1000, 500]
    assert mutation_ids == ["mutation-1", "mutation-2"]


def test_empty_input_makes_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_upsert_response_for("unused"))

    assert upsert(handler, []) == []
    assert calls == []


def test_non_2xx_response_raises_vector_store_error_with_codes_but_not_messages() -> None:
    handler = respond(403, {"errors": [{"code": 10001, "message": "secret detail"}]})

    with pytest.raises(VectorStoreError) as error:
        upsert(handler, [make_chunk(1)])

    assert "403" in str(error.value)
    assert "10001" in str(error.value)
    assert "secret detail" not in str(error.value)


def test_success_false_raises_vector_store_error() -> None:
    handler = respond(200, {"success": False, "errors": [{"code": 7003}]})

    with pytest.raises(VectorStoreError):
        upsert(handler, [make_chunk(1)])


def test_unparseable_body_raises_vector_store_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(VectorStoreError):
        upsert(handler, [make_chunk(1)])


def test_missing_mutation_id_raises_vector_store_error() -> None:
    handler = respond(200, {"result": {}, "success": True, "errors": []})

    with pytest.raises(VectorStoreError):
        upsert(handler, [make_chunk(1)])


def test_connect_error_raises_vector_store_error() -> None:
    with pytest.raises(VectorStoreError):
        upsert(raise_error(httpx.ConnectError("boom")), [make_chunk(1)])


def test_upsert_timeout_raises_vector_store_timeout_error() -> None:
    with pytest.raises(VectorStoreTimeoutError):
        upsert(raise_error(httpx.ReadTimeout("boom")), [make_chunk(1)])


def test_error_message_never_contains_the_token_or_metadata_text() -> None:
    handler = respond(403, {"errors": [{"code": 10001, "message": "unauthorized"}]})
    chunk = Chunk(id="chunk-1", vector=[0.1], metadata={"text": "a very specific policy sentence"})

    with pytest.raises(VectorStoreError) as error:
        upsert(handler, [chunk])

    assert "test-token" not in str(error.value)
    assert "a very specific policy sentence" not in str(error.value)


def test_query_posts_vector_and_top_k_with_metadata_requested() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_query_response_for([]))

    query(handler, [0.1, 0.2, 0.3], top_k=5)

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith("/vectorize/v2/indexes/champbot-policies/query")
    assert request.headers["authorization"] == "Bearer test-token"
    body = json.loads(request.content)
    assert body == {
        "vector": [0.1, 0.2, 0.3],
        "topK": 5,
        "returnValues": False,
        "returnMetadata": "all",
    }


def test_query_parses_matches_into_scored_chunks_in_order() -> None:
    matches = [
        {"id": "chunk-1", "score": 0.72, "metadata": {"title": "A", "text": "body a"}},
        {"id": "chunk-2", "score": 0.61, "metadata": {"title": "B", "text": "body b"}},
    ]
    handler = respond(200, _query_response_for(matches))

    scored = query(handler, [0.1], top_k=5)

    assert scored == [
        ScoredChunk(id="chunk-1", score=0.72, metadata={"title": "A", "text": "body a"}),
        ScoredChunk(id="chunk-2", score=0.61, metadata={"title": "B", "text": "body b"}),
    ]


def test_query_keeps_only_string_metadata_values() -> None:
    matches = [{"id": "chunk-1", "score": 0.5, "metadata": {"title": "A", "count": 3}}]
    handler = respond(200, _query_response_for(matches))

    scored = query(handler, [0.1], top_k=5)

    assert scored == [ScoredChunk(id="chunk-1", score=0.5, metadata={"title": "A"})]


def test_query_with_no_matches_returns_empty_list() -> None:
    handler = respond(200, _query_response_for([]))

    assert query(handler, [0.1], top_k=5) == []


def test_query_non_2xx_response_raises_vector_store_error_without_echoing_text() -> None:
    handler = respond(403, {"errors": [{"code": 10001, "message": "secret detail"}]})

    with pytest.raises(VectorStoreError) as error:
        query(handler, [0.1], top_k=5)

    assert "403" in str(error.value)
    assert "secret detail" not in str(error.value)


def test_query_success_false_raises_vector_store_error() -> None:
    handler = respond(200, {"success": False, "errors": [{"code": 7003}]})

    with pytest.raises(VectorStoreError):
        query(handler, [0.1], top_k=5)


def test_query_unparseable_body_raises_vector_store_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(VectorStoreError):
        query(handler, [0.1], top_k=5)


def test_query_timeout_raises_vector_store_timeout_error() -> None:
    with pytest.raises(VectorStoreTimeoutError):
        query(raise_error(httpx.ReadTimeout("boom")), [0.1], top_k=5)
