import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

Lookup = Callable[[str], object | None]


class MissingSettingError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Missing required setting: {name}")
        self.name = name


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str


def load_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> Settings:
    # On Workers, vars and secrets only reach Python through the env binding, not os.environ.
    lookup: Lookup = environ.get if workers_env is None else _attribute_lookup(workers_env)
    return Settings(
        gemini_api_key=_require_setting(lookup, "GEMINI_API_KEY"),
        gemini_model=_require_setting(lookup, "GEMINI_MODEL"),
    )


def _attribute_lookup(workers_env: object) -> Lookup:
    return lambda name: getattr(workers_env, name, None)


def _require_setting(lookup: Lookup, name: str) -> str:
    value = lookup(name)
    if not value:
        raise MissingSettingError(name)
    return str(value)
