from types import SimpleNamespace

import pytest

from champbot.common.core.domain.exceptions import MissingSettingError
from champbot.common.core.infrastructure.settings import (
    optional_setting,
    require_setting,
    settings_lookup,
)


def test_reads_a_setting_from_workers_env_attributes() -> None:
    lookup = settings_lookup(SimpleNamespace(SOME_SETTING="from-workers"), environ={})

    assert require_setting(lookup, "SOME_SETTING") == "from-workers"


def test_reads_a_setting_from_environ_without_workers_env() -> None:
    lookup = settings_lookup(None, environ={"SOME_SETTING": "from-environ"})

    assert require_setting(lookup, "SOME_SETTING") == "from-environ"


def test_prefers_workers_env_over_environ() -> None:
    lookup = settings_lookup(
        SimpleNamespace(SOME_SETTING="from-workers"), environ={"SOME_SETTING": "from-environ"}
    )

    assert require_setting(lookup, "SOME_SETTING") == "from-workers"


def test_does_not_fall_back_to_environ_for_a_setting_missing_from_workers_env() -> None:
    lookup = settings_lookup(SimpleNamespace(), environ={"SOME_SETTING": "from-environ"})

    with pytest.raises(MissingSettingError) as error:
        require_setting(lookup, "SOME_SETTING")

    assert error.value.name == "SOME_SETTING"


@pytest.mark.parametrize("missing_value", [None, ""])
@pytest.mark.parametrize("source", ["workers_env", "environ"])
def test_missing_or_empty_setting_raises_error_naming_it(
    source: str, missing_value: str | None
) -> None:
    values = {} if missing_value is None else {"SOME_SETTING": missing_value}
    if source == "workers_env":
        lookup = settings_lookup(SimpleNamespace(**values), environ={})
    else:
        lookup = settings_lookup(None, environ=values)

    with pytest.raises(MissingSettingError) as error:
        require_setting(lookup, "SOME_SETTING")

    assert error.value.name == "SOME_SETTING"


def test_optional_setting_returns_the_value_when_present() -> None:
    lookup = settings_lookup(None, environ={"SOME_SETTING": "from-environ"})

    assert optional_setting(lookup, "SOME_SETTING", "fallback") == "from-environ"


@pytest.mark.parametrize("missing_value", [None, ""])
def test_optional_setting_returns_the_default_when_missing_or_empty(
    missing_value: str | None,
) -> None:
    values = {} if missing_value is None else {"SOME_SETTING": missing_value}
    lookup = settings_lookup(None, environ=values)

    assert optional_setting(lookup, "SOME_SETTING", "fallback") == "fallback"
