import os
from collections.abc import Mapping
from dataclasses import dataclass

from champbot.common.core.infrastructure.settings import require_setting, settings_lookup


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    model: str


def load_gemini_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> GeminiSettings:
    lookup = settings_lookup(workers_env, environ)
    return GeminiSettings(
        api_key=require_setting(lookup, "GEMINI_API_KEY"),
        model=require_setting(lookup, "GEMINI_MODEL"),
    )
