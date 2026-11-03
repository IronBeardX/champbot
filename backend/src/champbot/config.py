import os
from collections.abc import Mapping
from dataclasses import dataclass

from champbot.common.core.infrastructure.settings import require_setting, settings_lookup


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str


def load_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> Settings:
    lookup = settings_lookup(workers_env, environ)
    return Settings(
        gemini_api_key=require_setting(lookup, "GEMINI_API_KEY"),
        gemini_model=require_setting(lookup, "GEMINI_MODEL"),
    )
