import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from champbot.common.embeddings.domain.embedder import EmbeddingError
from champbot.common.embeddings.infrastructure.workers_ai import WorkersAIEmbedder

Handler = Callable[[httpx.Request], httpx.Response]


# Shape from Cloudflare's public Workers AI docs for @cf/baai/bge-m3's `text` mode;
# not yet pinned from a live call (see the PR body for why).
def _response_for(vectors: list[list[float]]) -> dict[str, Any]:
    return {
        "result": {"shape": [len(vectors), len(vectors[0]) if vectors else 0], "data": vectors},
        "success": True,
        "errors": [],
        "messages": [],
    }


def embed(handler: Handler, texts: list[str]) -> list[list[float]]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedder = WorkersAIEmbedder(client, "test-account", "test-token")
    try:
        return asyncio.run(embedder.embed(texts))
    finally:
        asyncio.run(client.aclose())


def respond_with_vectors(vectors: list[list[float]]) -> Handler:
    return lambda _: httpx.Response(200, json=_response_for(vectors))


def respond(status_code: int, body: Any) -> Handler:
    return lambda _: httpx.Response(status_code, json=body)


def raise_error(error: Exception) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    return handler


def test_embeds_a_single_batch_with_the_text_mode_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response_for([[0.1, 0.2], [0.3, 0.4]]))

    vectors = embed(handler, ["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert len(requests) == 1
    sent_body = json.loads(requests[0].content)
    assert sent_body == {"text": ["hello", "world"]}
    assert "query" not in sent_body
    assert "contexts" not in sent_body
    assert requests[0].url.path.endswith("/ai/run/@cf/baai/bge-m3")
    assert requests[0].headers["authorization"] == "Bearer test-token"


def test_batches_more_than_fifty_texts_and_keeps_input_order() -> None:
    texts = [f"text-{i}" for i in range(120)]
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)["text"]
        requests.append(batch)
        return httpx.Response(200, json=_response_for([[float(len(requests))] for _ in batch]))

    vectors = embed(handler, texts)

    assert [len(batch) for batch in requests] == [50, 50, 20]
    assert vectors == [[1.0]] * 50 + [[2.0]] * 50 + [[3.0]] * 20


def test_empty_input_makes_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response_for([]))

    assert embed(handler, []) == []
    assert calls == []


def test_non_2xx_response_raises_embedding_error_with_codes_but_not_messages() -> None:
    handler = respond(401, {"errors": [{"code": 10000, "message": "secret detail"}]})

    with pytest.raises(EmbeddingError) as error:
        embed(handler, ["hello"])

    assert "401" in str(error.value)
    assert "10000" in str(error.value)
    assert "secret detail" not in str(error.value)


def test_success_false_raises_embedding_error() -> None:
    handler = respond(200, {"success": False, "errors": [{"code": 7003}]})

    with pytest.raises(EmbeddingError):
        embed(handler, ["hello"])


def test_unparseable_body_raises_embedding_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(EmbeddingError):
        embed(handler, ["hello"])


def test_fewer_vectors_than_texts_raises_embedding_error() -> None:
    handler = respond_with_vectors([[0.1, 0.2]])

    with pytest.raises(EmbeddingError):
        embed(handler, ["hello", "world"])


def test_connect_error_raises_embedding_error() -> None:
    handler = raise_error(httpx.ConnectError("boom"))

    with pytest.raises(EmbeddingError):
        embed(handler, ["hello"])


def test_timeout_raises_embedding_error() -> None:
    handler = raise_error(httpx.ReadTimeout("boom"))

    with pytest.raises(EmbeddingError):
        embed(handler, ["hello"])


def test_error_message_never_contains_the_token_or_input_text() -> None:
    handler = respond(401, {"errors": [{"code": 10000, "message": "unauthorized"}]})

    with pytest.raises(EmbeddingError) as error:
        embed(handler, ["a very specific policy sentence"])

    assert "test-token" not in str(error.value)
    assert "a very specific policy sentence" not in str(error.value)
