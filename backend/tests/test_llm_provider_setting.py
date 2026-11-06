from types import SimpleNamespace

import pytest

from champbot.common.core.domain.exceptions import InvalidSettingError, MissingSettingError
from champbot.common.llm.domain.provider import ProviderEnum
from champbot.common.llm.infrastructure.settings import load_llm_provider


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        pytest.param("gemini", ProviderEnum.GEMINI, id="gemini"),
        pytest.param("Gemini", ProviderEnum.GEMINI, id="gemini-mixed-case"),
        pytest.param("groq", ProviderEnum.GROQ, id="groq"),
        pytest.param("GROQ", ProviderEnum.GROQ, id="groq-upper-case"),
    ],
)
def test_reads_llm_provider_case_insensitively(raw_value: str, expected: ProviderEnum) -> None:
    assert load_llm_provider(None, {"LLM_PROVIDER": raw_value}) == expected


def test_reads_llm_provider_from_workers_env() -> None:
    workers_env = SimpleNamespace(LLM_PROVIDER="groq")

    assert load_llm_provider(workers_env, environ={}) == ProviderEnum.GROQ


def test_prefers_workers_env_over_environ_for_llm_provider() -> None:
    workers_env = SimpleNamespace(LLM_PROVIDER="groq")
    environ = {"LLM_PROVIDER": "gemini"}

    assert load_llm_provider(workers_env, environ) == ProviderEnum.GROQ


@pytest.mark.parametrize("missing_value", [None, ""])
def test_missing_or_empty_llm_provider_raises_error_naming_it(missing_value: str | None) -> None:
    environ = {} if missing_value is None else {"LLM_PROVIDER": missing_value}

    with pytest.raises(MissingSettingError) as error:
        load_llm_provider(None, environ)

    assert error.value.name == "LLM_PROVIDER"


def test_invalid_llm_provider_raises_error_naming_it() -> None:
    with pytest.raises(InvalidSettingError) as error:
        load_llm_provider(None, {"LLM_PROVIDER": "openai"})

    assert error.value.name == "LLM_PROVIDER"
