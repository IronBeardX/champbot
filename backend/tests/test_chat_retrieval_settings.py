from types import SimpleNamespace

import pytest

from champbot.chat.answer.infrastructure.settings import load_retrieval_settings
from champbot.common.core.domain.exceptions import InvalidSettingError, MissingSettingError


def test_reads_min_score_from_environ() -> None:
    settings = load_retrieval_settings(None, environ={"RETRIEVAL_MIN_SCORE": "0.55"})

    assert settings.min_score == 0.55


def test_reads_min_score_from_workers_env() -> None:
    settings = load_retrieval_settings(SimpleNamespace(RETRIEVAL_MIN_SCORE="0.6"), environ={})

    assert settings.min_score == 0.6


def test_missing_min_score_raises_missing_setting_error() -> None:
    with pytest.raises(MissingSettingError) as error:
        load_retrieval_settings(None, environ={})

    assert error.value.name == "RETRIEVAL_MIN_SCORE"


@pytest.mark.parametrize("bad_value", ["abc", "nan", "inf", "-inf"])
def test_non_numeric_or_non_finite_min_score_raises_invalid_setting_error(bad_value: str) -> None:
    with pytest.raises(InvalidSettingError) as error:
        load_retrieval_settings(None, environ={"RETRIEVAL_MIN_SCORE": bad_value})

    assert error.value.name == "RETRIEVAL_MIN_SCORE"
    assert bad_value not in str(error.value)
