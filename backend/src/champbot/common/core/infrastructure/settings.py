import os
from collections.abc import Callable, Mapping

from champbot.common.core.domain.exceptions import ChampBotError

Lookup = Callable[[str], object | None]


class MissingSettingError(ChampBotError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Missing required setting: {name}")
        self.name = name


def settings_lookup(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> Lookup:
    # On Workers, vars and secrets only reach Python through the env binding, not os.environ.
    return environ.get if workers_env is None else _attribute_lookup(workers_env)


def require_setting(lookup: Lookup, name: str) -> str:
    value = lookup(name)
    if not value:
        raise MissingSettingError(name)
    return str(value)


def _attribute_lookup(workers_env: object) -> Lookup:
    return lambda name: getattr(workers_env, name, None)
