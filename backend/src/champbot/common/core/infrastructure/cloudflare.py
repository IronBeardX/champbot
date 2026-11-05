import os
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from champbot.common.core.infrastructure.settings import require_setting, settings_lookup

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


@dataclass(frozen=True)
class CloudflareSettings:
    account_id: str
    api_token: str


def load_cloudflare_settings(
    token_setting: str,
    workers_env: object | None = None,
    environ: Mapping[str, str] = os.environ,
) -> CloudflareSettings:
    lookup = settings_lookup(workers_env, environ)
    return CloudflareSettings(
        account_id=require_setting(lookup, "CLOUDFLARE_ACCOUNT_ID"),
        api_token=require_setting(lookup, token_setting),
    )


def describe_cloudflare_errors(response: httpx.Response) -> str:
    # Error bodies can echo the request, so only Cloudflare's numeric codes reach the logs.
    try:
        codes = [str(error["code"]) for error in response.json()["errors"]]
    except (ValueError, KeyError, TypeError):
        return "no codes"
    return f"codes={','.join(codes)}" if codes else "no codes"
