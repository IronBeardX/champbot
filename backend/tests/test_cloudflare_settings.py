from types import SimpleNamespace

import httpx
import pytest

from champbot.common.core.domain.exceptions import MissingSettingError
from champbot.common.core.infrastructure.cloudflare import (
    CloudflareSettings,
    describe_cloudflare_errors,
    load_cloudflare_settings,
)

EXPECTED = CloudflareSettings(account_id="test-account", api_token="test-token")


def test_reads_settings_from_environ_using_the_named_token() -> None:
    environ = {"CLOUDFLARE_ACCOUNT_ID": "test-account", "CF_INGEST_API_TOKEN": "test-token"}

    assert load_cloudflare_settings("CF_INGEST_API_TOKEN", environ=environ) == EXPECTED


def test_a_different_token_setting_name_reads_a_different_variable() -> None:
    environ = {
        "CLOUDFLARE_ACCOUNT_ID": "test-account",
        "CF_INGEST_API_TOKEN": "ingest-token",
        "CF_RUNTIME_API_TOKEN": "runtime-token",
    }

    settings = load_cloudflare_settings("CF_RUNTIME_API_TOKEN", environ=environ)

    assert settings.api_token == "runtime-token"


def test_reads_settings_from_workers_env() -> None:
    workers_env = SimpleNamespace(
        CLOUDFLARE_ACCOUNT_ID="test-account", CF_INGEST_API_TOKEN="test-token"
    )

    assert load_cloudflare_settings("CF_INGEST_API_TOKEN", workers_env, environ={}) == EXPECTED


def test_missing_account_id_raises_error_naming_it() -> None:
    environ = {"CF_INGEST_API_TOKEN": "test-token"}

    with pytest.raises(MissingSettingError) as error:
        load_cloudflare_settings("CF_INGEST_API_TOKEN", environ=environ)

    assert error.value.name == "CLOUDFLARE_ACCOUNT_ID"


def test_missing_token_raises_error_naming_the_passed_token_setting() -> None:
    environ = {"CLOUDFLARE_ACCOUNT_ID": "test-account"}

    with pytest.raises(MissingSettingError) as error:
        load_cloudflare_settings("CF_RUNTIME_API_TOKEN", environ=environ)

    assert error.value.name == "CF_RUNTIME_API_TOKEN"


def test_describe_cloudflare_errors_joins_the_numeric_codes_only() -> None:
    response = httpx.Response(
        400,
        json={"errors": [{"code": 10000, "message": "secret token details"}, {"code": 7003}]},
    )

    description = describe_cloudflare_errors(response)

    assert description == "codes=10000,7003"
    assert "secret token details" not in description


def test_describe_cloudflare_errors_falls_back_on_an_unparseable_body() -> None:
    assert describe_cloudflare_errors(httpx.Response(500, text="not json")) == "no codes"
