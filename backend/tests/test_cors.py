import pytest
from fastapi.testclient import TestClient

from champbot.main import create_app

ALLOWED_ORIGINS = [
    "https://champbot-frontend.alejandroyeroval.workers.dev",
    "http://localhost:8788",
    "http://127.0.0.1:8788",
]

DISALLOWED_ORIGINS = [
    "https://champbot-frontend.alejandroyeroval.workers.dev.evil.com",
    "https://evilchampbot-frontend.other.workers.dev",
    "http://champbot-frontend.alejandroyeroval.workers.dev",
]


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_preflight_allows_the_frontend_origins(origin: str) -> None:
    client = TestClient(create_app())

    response = client.options(
        "/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", DISALLOWED_ORIGINS)
def test_preflight_rejects_lookalike_origins(origin: str) -> None:
    client = TestClient(create_app())

    response = client.options(
        "/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_can_read_the_retry_after_header() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/health", headers={"Origin": "https://champbot-frontend.alejandroyeroval.workers.dev"}
    )

    assert "Retry-After" in response.headers["access-control-expose-headers"]
