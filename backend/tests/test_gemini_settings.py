"""Repeats the core settings rules on purpose.

They check that the Gemini loader goes through the core lookup.
"""

from types import SimpleNamespace

import pytest

from champbot.common.core.domain.exceptions import InvalidSettingError, MissingSettingError
from champbot.common.llm.infrastructure.settings import GeminiSettings, load_gemini_settings

EXPECTED = GeminiSettings(api_key="test-key", model="test-model", thinking_level="LOW")


def test_reads_gemini_settings_from_workers_env() -> None:
    workers_env = SimpleNamespace(GEMINI_API_KEY="test-key", GEMINI_MODEL="test-model")

    assert load_gemini_settings(workers_env, environ={}) == EXPECTED


def test_reads_gemini_settings_from_environ_without_workers_env() -> None:
    environ = {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}

    assert load_gemini_settings(None, environ) == EXPECTED


def test_prefers_workers_env_over_environ_for_gemini_settings() -> None:
    workers_env = SimpleNamespace(GEMINI_API_KEY="test-key", GEMINI_MODEL="test-model")
    environ = {"GEMINI_API_KEY": "other-key", "GEMINI_MODEL": "other-model"}

    assert load_gemini_settings(workers_env, environ) == EXPECTED


def test_does_not_fall_back_to_environ_for_a_gemini_setting_missing_from_workers_env() -> None:
    workers_env = SimpleNamespace(GEMINI_API_KEY="test-key")
    environ = {"GEMINI_API_KEY": "other-key", "GEMINI_MODEL": "other-model"}

    with pytest.raises(MissingSettingError) as error:
        load_gemini_settings(workers_env, environ)

    assert error.value.name == "GEMINI_MODEL"


@pytest.mark.parametrize("missing_name", ["GEMINI_API_KEY", "GEMINI_MODEL"])
@pytest.mark.parametrize("missing_value", [None, ""])
@pytest.mark.parametrize("source", ["workers_env", "environ"])
def test_missing_or_empty_gemini_setting_raises_error_naming_it(
    source: str, missing_value: str | None, missing_name: str
) -> None:
    values = {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}
    del values[missing_name]
    if missing_value is not None:
        values[missing_name] = missing_value

    with pytest.raises(MissingSettingError) as error:
        if source == "workers_env":
            load_gemini_settings(SimpleNamespace(**values), environ={})
        else:
            load_gemini_settings(None, values)

    assert error.value.name == missing_name


@pytest.mark.parametrize("missing_value", [None, ""])
def test_gemini_thinking_level_defaults_to_low_when_absent_or_empty(
    missing_value: str | None,
) -> None:
    environ = {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}
    if missing_value is not None:
        environ["GEMINI_THINKING_LEVEL"] = missing_value

    assert load_gemini_settings(None, environ).thinking_level == "LOW"


@pytest.mark.parametrize("raw_value", ["medium", "Medium", "MEDIUM"])
def test_gemini_thinking_level_is_normalized_to_upper_case(raw_value: str) -> None:
    environ = {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "test-model",
        "GEMINI_THINKING_LEVEL": raw_value,
    }

    assert load_gemini_settings(None, environ).thinking_level == "MEDIUM"


def test_invalid_gemini_thinking_level_raises_error_naming_it() -> None:
    environ = {
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "test-model",
        "GEMINI_THINKING_LEVEL": "FAST",
    }

    with pytest.raises(InvalidSettingError) as error:
        load_gemini_settings(None, environ)

    assert error.value.name == "GEMINI_THINKING_LEVEL"


def test_reads_gemini_thinking_level_from_workers_env() -> None:
    workers_env = SimpleNamespace(
        GEMINI_API_KEY="test-key", GEMINI_MODEL="test-model", GEMINI_THINKING_LEVEL="HIGH"
    )

    assert load_gemini_settings(workers_env, environ={}).thinking_level == "HIGH"
