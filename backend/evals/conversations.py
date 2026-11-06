import argparse
import asyncio
import email.utils
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from champbot.chat.answer.application.flight_results import today_in_ist
from champbot.chat.answer.presentation.serializers import ChatRequest, ChatResponse
from evals.conversation_metrics import (
    CaseResult,
    CaseSpec,
    CheckResult,
    TurnExpectation,
    TurnResult,
    build_history,
    classify_case,
    load_cases,
    render_message,
    run_checks,
    summarize,
)
from evals.conversation_report import ReportHeader, render_report
from evals.git_info import REPO_ROOT, git_sha

DEFAULT_CASES_FILE = Path(__file__).parents[1] / "data" / "eval" / "conversations.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "eval" / "conversations.md"
DEFAULT_BASE_URL = "https://champbot.alejandroyeroval.workers.dev"

MIN_INTERVAL_SECONDS = 6.0
RETRY_AFTER_DEFAULT_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 120.0
MAX_RETRIES = 2
RETRYABLE_STATUSES = {429, 503}
BREAKER_STATUS = 429
REQUEST_TIMEOUT_SECONDS = 30.0

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Now = Callable[[], datetime]


class Pacer:
    def __init__(self, min_interval: float, sleep: Sleep, clock: Clock) -> None:
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_start: float | None = None

    async def wait_turn(self) -> None:
        if self._last_start is not None:
            remaining = self._min_interval - (self._clock() - self._last_start)
            if remaining > 0:
                await self._sleep(remaining)
        self._last_start = self._clock()


def main(
    argv: list[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = time.monotonic,
    now: Now = lambda: datetime.now(UTC),
) -> int:
    args = _parse_args(argv)

    try:
        all_cases = load_cases(DEFAULT_CASES_FILE)
    except (OSError, ValueError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    try:
        cases = _select_cases(all_cases, case_id=args.case, limit=args.limit)
    except KeyError as error:
        print(error, file=sys.stderr)
        return 1

    if args.dry_run:
        return _dry_run(cases, now)

    model_label = (
        f"{args.model} (stated by operator)" if args.model else "unknown (not reported by /chat)"
    )

    results = asyncio.run(_run_cases(cases, args.base_url, transport, sleep, clock, now))
    summary = summarize(results)
    header = ReportHeader(
        run_date_utc=now(),
        commit_sha=git_sha(),
        base_url=args.base_url,
        model=model_label,
        case_count=len(cases),
        turn_count=sum(len(case.turns) for case in cases),
        pacing_seconds=MIN_INTERVAL_SECONDS,
        max_retries=MAX_RETRIES,
    )
    markdown = render_report(header, results, summary)

    filtered = args.case is not None or args.limit is not None
    if args.output is not None:
        output_path: Path | None = args.output
    elif filtered:
        output_path = None
    else:
        output_path = DEFAULT_OUTPUT

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown)
        print(f"wrote {output_path}")
    else:
        print(markdown)

    breaker_tripped = any(case.outcome == "not_run" for case in results)
    return 1 if breaker_tripped else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="champbot-eval-conversations")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", default=None)
    selection.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def _select_cases(cases: list[CaseSpec], case_id: str | None, limit: int | None) -> list[CaseSpec]:
    if case_id is not None:
        for case in cases:
            if case.id == case_id:
                return [case]
        raise KeyError(f"no case with id {case_id!r}")
    if limit is not None:
        return cases[:limit]
    return cases


def _build_chat_request(message: str, pairs: list[tuple[str, str]]) -> ChatRequest:
    return ChatRequest.model_validate({"message": message, "history": build_history(pairs)})


def _dry_run(cases: list[CaseSpec], now: Now) -> int:
    today = today_in_ist(now())
    total_turns = 0
    for case in cases:
        print(f"case {case.id} ({case.language}, {case.category}):")
        pairs: list[tuple[str, str]] = []
        for turn_index, expectation in enumerate(case.turns):
            rendered = render_message(expectation.message, today)
            request = _build_chat_request(rendered, pairs)
            print(f"  turn {turn_index}: {rendered!r} (history items={len(request.history)})")
            pairs.append((rendered, "<dry-run placeholder answer>"))
            total_turns += 1
    min_duration = total_turns * MIN_INTERVAL_SECONDS
    print(
        f"{len(cases)} cases, {total_turns} turns, "
        f"minimum duration ~{min_duration:.0f}s from pacing alone"
    )
    return 0


async def _run_cases(
    cases: list[CaseSpec],
    base_url: str,
    transport: httpx.AsyncBaseTransport | None,
    sleep: Sleep,
    clock: Clock,
    now: Now,
) -> list[CaseResult]:
    pacer = Pacer(MIN_INTERVAL_SECONDS, sleep, clock)
    results: list[CaseResult] = []
    breaker_tripped = False

    client_kwargs: dict[str, Any] = {"timeout": REQUEST_TIMEOUT_SECONDS}
    if transport is not None:
        client_kwargs["transport"] = transport
    async with httpx.AsyncClient(**client_kwargs) as client:
        for case in cases:
            if breaker_tripped:
                results.append(CaseResult(case.id, case.language, case.category, [], "not_run"))
                continue

            turn_results: list[TurnResult] = []
            pairs: list[tuple[str, str]] = []
            for turn_index, expectation in enumerate(case.turns):
                today = today_in_ist(now())
                rendered_message = render_message(expectation.message, today)
                chat_request = _build_chat_request(rendered_message, pairs)

                turn_result, trip_breaker = await _send_turn(
                    client,
                    pacer,
                    base_url,
                    chat_request,
                    expectation,
                    case.language,
                    turn_index,
                    sleep,
                    clock,
                    now,
                )
                turn_results.append(turn_result)
                if trip_breaker:
                    breaker_tripped = True

                has_valid_answer = turn_result.status == "200" and not any(
                    check.name == "contract" and not check.passed for check in turn_result.checks
                )
                if not has_valid_answer:
                    break
                pairs.append((rendered_message, turn_result.answer or ""))

            results.append(
                CaseResult(
                    case.id, case.language, case.category, turn_results, classify_case(turn_results)
                )
            )
    return results


async def _send_turn(
    client: httpx.AsyncClient,
    pacer: Pacer,
    base_url: str,
    chat_request: ChatRequest,
    expectation: TurnExpectation,
    language: str,
    turn_index: int,
    sleep: Sleep,
    clock: Clock,
    now: Now,
) -> tuple[TurnResult, bool]:
    attempt = 0
    while True:
        await pacer.wait_turn()
        start = clock()
        try:
            response = await client.post(
                f"{base_url}/chat", json=chat_request.model_dump(mode="json")
            )
        except httpx.TransportError:
            latency = clock() - start
            return (
                TurnResult(turn_index, expectation.message, "transport", [], None, latency),
                False,
            )

        latency = clock() - start
        status = response.status_code

        if status == 200:
            try:
                parsed = ChatResponse.model_validate_json(response.text)
            except ValidationError as error:
                checks = [CheckResult("contract", False, "valid ChatResponse", str(error))]
                return (
                    TurnResult(turn_index, expectation.message, "200", checks, None, latency),
                    False,
                )
            source_urls = [source.url for source in parsed.sources]
            checks = run_checks(
                expectation,
                language,
                parsed.intent,
                source_urls,
                len(parsed.flights),
                parsed.answer,
            )
            return (
                TurnResult(turn_index, expectation.message, "200", checks, parsed.answer, latency),
                False,
            )

        if status in RETRYABLE_STATUSES and attempt < MAX_RETRIES:
            wait = _retry_wait_seconds(response.headers.get("retry-after"), now())
            if wait is None:
                return (
                    TurnResult(turn_index, expectation.message, str(status), [], None, latency),
                    status == BREAKER_STATUS,
                )
            attempt += 1
            await sleep(wait)
            continue

        return (
            TurnResult(turn_index, expectation.message, str(status), [], None, latency),
            status == BREAKER_STATUS,
        )


def _retry_wait_seconds(header_value: str | None, now: datetime) -> float | None:
    parsed = _parse_retry_after(header_value, now)
    wait = RETRY_AFTER_DEFAULT_SECONDS if parsed is None else parsed
    if wait > RETRY_AFTER_CAP_SECONDS:
        return None
    return max(wait, 0.0)


def _parse_retry_after(header_value: str | None, now: datetime) -> float | None:
    if header_value is None:
        return None
    header_value = header_value.strip()
    try:
        return float(header_value)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - now).total_seconds()


if __name__ == "__main__":
    sys.exit(main())
