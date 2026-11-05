import os
from collections.abc import Mapping
from dataclasses import dataclass

from champbot.common.core.domain.exceptions import InvalidSettingError
from champbot.common.core.infrastructure.settings import (
    optional_setting,
    require_setting,
    settings_lookup,
)

_THINKING_LEVEL_SETTING = "GEMINI_THINKING_LEVEL"
_DEFAULT_THINKING_LEVEL = "LOW"
_VALID_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    model: str
    thinking_level: str


def load_gemini_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> GeminiSettings:
    lookup = settings_lookup(workers_env, environ)
    thinking_level = optional_setting(
        lookup, _THINKING_LEVEL_SETTING, _DEFAULT_THINKING_LEVEL
    ).upper()
    if thinking_level not in _VALID_THINKING_LEVELS:
        raise InvalidSettingError(_THINKING_LEVEL_SETTING)
    return GeminiSettings(
        api_key=require_setting(lookup, "GEMINI_API_KEY"),
        model=require_setting(lookup, "GEMINI_MODEL"),
        thinking_level=thinking_level,
    )
