import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

from champbot.common.core.domain.exceptions import InvalidSettingError
from champbot.common.core.infrastructure.settings import require_setting, settings_lookup

_MIN_SCORE_SETTING = "RETRIEVAL_MIN_SCORE"


@dataclass(frozen=True)
class RetrievalSettings:
    min_score: float


def load_retrieval_settings(
    workers_env: object | None = None, environ: Mapping[str, str] = os.environ
) -> RetrievalSettings:
    lookup = settings_lookup(workers_env, environ)
    raw_min_score = require_setting(lookup, _MIN_SCORE_SETTING)
    try:
        min_score = float(raw_min_score)
    except ValueError as error:
        raise InvalidSettingError(_MIN_SCORE_SETTING) from error
    if not math.isfinite(min_score):
        raise InvalidSettingError(_MIN_SCORE_SETTING)
    return RetrievalSettings(min_score=min_score)
