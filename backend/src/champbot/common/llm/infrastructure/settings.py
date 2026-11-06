import os
from collections.abc import Mapping
from dataclasses import dataclass

from champbot.common.core.domain.exceptions import InvalidSettingError
from champbot.common.core.infrastructure.settings import (
    optional_setting,
    require_setting,
    settings_lookup,
)
from champbot.common.llm.domain.provider import ProviderEnum

_LLM_PROVIDER_SETTING = "LLM_PROVIDER"
_THINKING_LEVEL_SETTING = "GEMINI_THINKING_LEVEL"
_GROQ_REASONING_EFFORT_SETTING = "GROQ_REASONING_EFFORT"
_DEFAULT_THINKING_LEVEL = "LOW"
_VALID_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    model: str
    generate_content_url: str
    thinking_level: str


@dataclass(frozen=True)
class GroqSettings:
    api_key: str
    model: str
    generate_content_url: str
    thinking_level: str | None


def load_llm_provider(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> ProviderEnum:
    lookup = settings_lookup(workers_env, environ)
    raw_value = require_setting(lookup, _LLM_PROVIDER_SETTING).strip().lower()
    try:
        return ProviderEnum(raw_value)
    except ValueError:
        raise InvalidSettingError(_LLM_PROVIDER_SETTING) from None


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
        generate_content_url=require_setting(lookup, "GEMINI_GENERATE_CONTENT_URL"),
        thinking_level=thinking_level,
    )


def load_groq_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> GroqSettings:
    lookup = settings_lookup(workers_env, environ)

    reasoning_effort = (
        optional_setting(
            lookup,
            _GROQ_REASONING_EFFORT_SETTING,
            "",
        )
        .strip()
        .lower()
        or None
    )

    if reasoning_effort is not None and reasoning_effort not in {
        "none",
        "low",
        "medium",
        "high",
    }:
        raise InvalidSettingError(_GROQ_REASONING_EFFORT_SETTING)

    return GroqSettings(
        api_key=require_setting(lookup, "GROQ_API_KEY"),
        model=require_setting(lookup, "GROQ_MODEL"),
        generate_content_url=require_setting(lookup, "GROQ_GENERATE_CONTENT_URL"),
        thinking_level=reasoning_effort,
    )
