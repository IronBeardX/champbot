import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from champbot.common.vector_store.domain.store import Chunk, VectorStoreError
from champbot.common.vector_store.infrastructure.vectorize import VectorizeStore

Handler = Callable[[httpx.Request], httpx.Response]


# Shape pinned from a live Vectorize v2 upsert call on 2026-11-05 (one throwaway vector).
def _response_for(mutation_id: str) -> dict[str, Any]:
    return {
        "result": {"mutationId": mutation_id},
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
        return httpx.Response(200, json=_response_for("mutation-1"))

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
        return httpx.Response(200, json=_response_for(f"mutation-{len(batch_sizes)}"))

    mutation_ids = upsert(handler, chunks)

    assert batch_sizes == [1000, 500]
    assert mutation_ids == ["mutation-1", "mutation-2"]


def test_empty_input_makes_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response_for("unused"))

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


def test_timeout_raises_vector_store_error() -> None:
    with pytest.raises(VectorStoreError):
        upsert(raise_error(httpx.ReadTimeout("boom")), [make_chunk(1)])


def test_error_message_never_contains_the_token_or_metadata_text() -> None:
    handler = respond(403, {"errors": [{"code": 10001, "message": "unauthorized"}]})
    chunk = Chunk(id="chunk-1", vector=[0.1], metadata={"text": "a very specific policy sentence"})

    with pytest.raises(VectorStoreError) as error:
        upsert(handler, [chunk])

    assert "test-token" not in str(error.value)
    assert "a very specific policy sentence" not in str(error.value)
