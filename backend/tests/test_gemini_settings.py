"""Repeats the core settings rules on purpose.

They check that the Gemini loader goes through the core lookup.
"""

from types import SimpleNamespace

import pytest

from champbot.common.core.domain.exceptions import MissingSettingError
from champbot.common.llm.infrastructure.settings import GeminiSettings, load_gemini_settings

EXPECTED = GeminiSettings(api_key="test-key", model="test-model")


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
