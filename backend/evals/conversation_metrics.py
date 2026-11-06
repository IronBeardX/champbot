import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from champbot.chat.answer.presentation.serializers import (
    MAX_ASSISTANT_TEXT_LENGTH,
    MAX_HISTORY_ITEMS,
    MAX_HISTORY_TEXT_LENGTH,
    MAX_USER_TEXT_LENGTH,
)

Outcome = Literal["pass", "fail", "http_error", "not_run"]

_DATE_PLACEHOLDER = re.compile(r"\{date([+-]\d+)\}")
_DEVANAGARI_START = 0x0900
_DEVANAGARI_END = 0x097F
_HI_MIN_SHARE = 0.5
_EN_MAX_SHARE = 0.05


@dataclass(frozen=True)
class TurnExpectation:
    message: str
    intent: str
    flights: bool
    cited_url: str | None = None
    off_topic: bool = False


@dataclass(frozen=True)
class CaseSpec:
    id: str
    language: str
    category: str
    turns: list[TurnExpectation]


def load_cases(path: Path) -> list[CaseSpec]:
    raw: Any = json.loads(path.read_text())
    try:
        cases = [
            CaseSpec(
                id=entry["id"],
                language=entry["language"],
                category=entry["category"],
                turns=[
                    TurnExpectation(
                        message=turn["message"],
                        intent=turn["intent"],
                        flights=turn["flights"],
                        cited_url=turn.get("cited_url"),
                        off_topic=turn.get("off_topic", False),
                    )
                    for turn in entry["turns"]
                ],
            )
            for entry in raw["cases"]
        ]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{path}: unexpected shape ({error})") from error
    return cases


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass(frozen=True)
class TurnResult:
    turn_index: int
    message: str
    status: str
    checks: list[CheckResult]
    answer: str | None
    latency_seconds: float | None


@dataclass(frozen=True)
class CaseResult:
    id: str
    language: str
    category: str
    turns: list[TurnResult]
    outcome: Outcome


@dataclass(frozen=True)
class LatencySummary:
    n: int
    p50: float | None
    p95: float | None


@dataclass(frozen=True)
class RunSummary:
    outcome_counts: dict[Outcome, int]
    status_counts: dict[str, int]
    category_language_counts: dict[tuple[str, str], dict[Outcome, int]]
    latency: LatencySummary


def render_message(text: str, today: date) -> str:
    def _replace(match: re.Match[str]) -> str:
        offset = int(match.group(1))
        return (today + timedelta(days=offset)).isoformat()

    rendered = _DATE_PLACEHOLDER.sub(_replace, text)
    if "{date" in rendered:
        raise ValueError(f"unrendered date placeholder in: {text!r}")
    return rendered


def _fits_alone(user_text: str, assistant_text: str) -> bool:
    return (
        bool(user_text.strip())
        and bool(assistant_text.strip())
        and len(user_text) <= MAX_USER_TEXT_LENGTH
        and len(assistant_text) <= MAX_ASSISTANT_TEXT_LENGTH
    )


def build_history(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    eligible = [pair for pair in pairs if _fits_alone(*pair)]

    kept: list[tuple[str, str]] = []
    item_count = 0
    char_total = 0
    for user_text, assistant_text in reversed(eligible):
        pair_length = len(user_text) + len(assistant_text)
        if item_count + 2 > MAX_HISTORY_ITEMS or char_total + pair_length > MAX_HISTORY_TEXT_LENGTH:
            break
        kept.insert(0, (user_text, assistant_text))
        item_count += 2
        char_total += pair_length

    history: list[dict[str, str]] = []
    for user_text, assistant_text in kept:
        history.append({"role": "user", "text": user_text})
        history.append({"role": "assistant", "text": assistant_text})
    return history


def devanagari_share(text: str) -> float:
    devanagari = 0
    other_alpha = 0
    for char in text:
        code_point = ord(char)
        if _DEVANAGARI_START <= code_point <= _DEVANAGARI_END:
            devanagari += 1
        elif char.isalpha():
            other_alpha += 1
    total = devanagari + other_alpha
    if total == 0:
        return 0.0
    return devanagari / total


def check_intent(expected: str, actual: str) -> CheckResult:
    return CheckResult("intent", expected == actual, expected, actual)


def check_cited_url(expected_url: str, source_urls: list[str]) -> CheckResult:
    passed = expected_url in source_urls
    actual = ", ".join(source_urls) if source_urls else "(none)"
    return CheckResult("cited_url", passed, expected_url, actual)


def check_flights_presence(expected_has_flights: bool, flights_count: int) -> CheckResult:
    actual_has_flights = flights_count > 0
    return CheckResult(
        "flights_presence",
        expected_has_flights == actual_has_flights,
        "non-empty" if expected_has_flights else "empty",
        "non-empty" if actual_has_flights else "empty",
    )


def check_language(expected_language: str, answer: str) -> CheckResult:
    share = devanagari_share(answer)
    if expected_language == "hi":
        passed = share > _HI_MIN_SHARE
        expected_description = f"devanagari share > {_HI_MIN_SHARE}"
    else:
        passed = share < _EN_MAX_SHARE
        expected_description = f"devanagari share < {_EN_MAX_SHARE}"
    return CheckResult("language", passed, expected_description, f"{share:.3f}")


def check_off_topic_shape(intent: str, source_urls: list[str], flights_count: int) -> CheckResult:
    violations: list[str] = []
    if intent != "general":
        violations.append(f"intent={intent}")
    if source_urls:
        violations.append(f"sources={len(source_urls)}")
    if flights_count:
        violations.append(f"flights={flights_count}")
    return CheckResult(
        "off_topic_shape",
        not violations,
        "general, no sources, no flights",
        "; ".join(violations) if violations else "ok",
    )


def run_checks(
    expectation: TurnExpectation,
    language: str,
    intent: str,
    source_urls: list[str],
    flights_count: int,
    answer: str,
) -> list[CheckResult]:
    checks: list[CheckResult] = [check_intent(expectation.intent, intent)]
    if expectation.off_topic:
        checks.append(check_off_topic_shape(intent, source_urls, flights_count))
        return checks
    if expectation.cited_url is not None:
        checks.append(check_cited_url(expectation.cited_url, source_urls))
    checks.append(check_flights_presence(expectation.flights, flights_count))
    if expectation.intent != "flight_search":
        checks.append(check_language(language, answer))
    return checks


def classify_case(turns: list[TurnResult]) -> Outcome:
    if not turns:
        return "not_run"
    if any(turn.status != "200" for turn in turns):
        return "http_error"
    if any(not check.passed for turn in turns for check in turn.checks):
        return "fail"
    return "pass"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    index = max(0, math.ceil(pct / 100 * n) - 1)
    return ordered[index]


def summarize_latency(values: list[float]) -> LatencySummary:
    return LatencySummary(n=len(values), p50=percentile(values, 50), p95=percentile(values, 95))


def summarize(cases: list[CaseResult]) -> RunSummary:
    outcome_counts: dict[Outcome, int] = {}
    status_counts: dict[str, int] = {}
    category_language_counts: dict[tuple[str, str], dict[Outcome, int]] = {}

    for case in cases:
        outcome_counts[case.outcome] = outcome_counts.get(case.outcome, 0) + 1
        key = (case.category, case.language)
        bucket = category_language_counts.setdefault(key, {})
        bucket[case.outcome] = bucket.get(case.outcome, 0) + 1
        for turn in case.turns:
            status_counts[turn.status] = status_counts.get(turn.status, 0) + 1

    latencies = [
        turn.latency_seconds
        for case in cases
        for turn in case.turns
        if turn.latency_seconds is not None
    ]
    return RunSummary(
        outcome_counts=outcome_counts,
        status_counts=status_counts,
        category_language_counts=category_language_counts,
        latency=summarize_latency(latencies),
    )


def truncate_answer(text: str, limit: int = 300) -> str:
    escaped = text.replace("|", "\\|").replace("\n", " ")
    code_points = list(escaped)
    if len(code_points) <= limit:
        return escaped
    return "".join(code_points[:limit]) + "…"
