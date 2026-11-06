"""Repeats the core settings rules on purpose.

They check that the Groq loader goes through the core lookup.
"""

from types import SimpleNamespace

import pytest

from champbot.common.core.domain.exceptions import InvalidSettingError, MissingSettingError
from champbot.common.llm.infrastructure.settings import GroqSettings, load_groq_settings

BASE_VALUES = {
    "GROQ_API_KEY": "test-key",
    "GROQ_MODEL": "test-model",
    "GROQ_GENERATE_CONTENT_URL": "https://test.example/chat/completions",
}

EXPECTED = GroqSettings(
    api_key="test-key",
    model="test-model",
    generate_content_url="https://test.example/chat/completions",
    thinking_level=None,
)


def test_reads_groq_settings_from_workers_env() -> None:
    workers_env = SimpleNamespace(**BASE_VALUES)

    assert load_groq_settings(workers_env, environ={}) == EXPECTED


def test_reads_groq_settings_from_environ_without_workers_env() -> None:
    assert load_groq_settings(None, BASE_VALUES) == EXPECTED


def test_prefers_workers_env_over_environ_for_groq_settings() -> None:
    workers_env = SimpleNamespace(**BASE_VALUES)
    environ = {
        "GROQ_API_KEY": "other-key",
        "GROQ_MODEL": "other-model",
        "GROQ_GENERATE_CONTENT_URL": "https://other.example/chat/completions",
    }

    assert load_groq_settings(workers_env, environ) == EXPECTED


def test_does_not_fall_back_to_environ_for_a_groq_setting_missing_from_workers_env() -> None:
    workers_env = SimpleNamespace(GROQ_API_KEY="test-key")
    environ = {
        "GROQ_API_KEY": "other-key",
        "GROQ_MODEL": "other-model",
        "GROQ_GENERATE_CONTENT_URL": "https://other.example/chat/completions",
    }

    with pytest.raises(MissingSettingError) as error:
        load_groq_settings(workers_env, environ)

    assert error.value.name == "GROQ_MODEL"


@pytest.mark.parametrize(
    "missing_name", ["GROQ_API_KEY", "GROQ_MODEL", "GROQ_GENERATE_CONTENT_URL"]
)
@pytest.mark.parametrize("missing_value", [None, ""])
@pytest.mark.parametrize("source", ["workers_env", "environ"])
def test_missing_or_empty_groq_setting_raises_error_naming_it(
    source: str, missing_value: str | None, missing_name: str
) -> None:
    values = dict(BASE_VALUES)
    del values[missing_name]
    if missing_value is not None:
        values[missing_name] = missing_value

    with pytest.raises(MissingSettingError) as error:
        if source == "workers_env":
            load_groq_settings(SimpleNamespace(**values), environ={})
        else:
            load_groq_settings(None, values)

    assert error.value.name == missing_name


@pytest.mark.parametrize("missing_value", [None, ""])
def test_groq_reasoning_effort_defaults_to_none_when_absent_or_empty(
    missing_value: str | None,
) -> None:
    environ = dict(BASE_VALUES)
    if missing_value is not None:
        environ["GROQ_REASONING_EFFORT"] = missing_value

    assert load_groq_settings(None, environ).thinking_level is None


@pytest.mark.parametrize("raw_value", ["medium", "Medium", "MEDIUM"])
def test_groq_reasoning_effort_is_normalized_to_lower_case(raw_value: str) -> None:
    environ = {**BASE_VALUES, "GROQ_REASONING_EFFORT": raw_value}

    assert load_groq_settings(None, environ).thinking_level == "medium"


def test_invalid_groq_reasoning_effort_raises_error_naming_it() -> None:
    environ = {**BASE_VALUES, "GROQ_REASONING_EFFORT": "fast"}

    with pytest.raises(InvalidSettingError) as error:
        load_groq_settings(None, environ)

    assert error.value.name == "GROQ_REASONING_EFFORT"


def test_reads_groq_reasoning_effort_from_workers_env() -> None:
    workers_env = SimpleNamespace(**BASE_VALUES, GROQ_REASONING_EFFORT="high")

    assert load_groq_settings(workers_env, environ={}).thinking_level == "high"
