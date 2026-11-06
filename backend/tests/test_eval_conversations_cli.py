import email.utils
import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from evals.conversations import main

FIXED_NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
Handler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class RecordingSleep:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self._clock.value += seconds


def fake_now() -> datetime:
    return FIXED_NOW


def ok_body(
    intent: str = "policy",
    answer: str = "Here is the answer, in plain English.",
    sources: list[dict[str, str]] | None = None,
    flights: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "answer": answer,
        "sources": sources or [],
        "flights": flights or [],
        "flights_note": None,
    }


def request_message(request: httpx.Request) -> str:
    body: Any = json.loads(request.content)
    return body["message"]


def run(
    argv: list[str],
    handler: Handler,
    clock: FakeClock | None = None,
    sleep: RecordingSleep | None = None,
) -> tuple[int, RecordingSleep]:
    clock = clock or FakeClock()
    sleep = sleep or RecordingSleep(clock)
    transport = httpx.MockTransport(handler)
    exit_code = main(argv, transport=transport, sleep=sleep, clock=clock, now=fake_now)
    return exit_code, sleep


async def _constant_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=ok_body())


def test_end_to_end_with_limit_and_output_writes_a_full_report(tmp_path: Path) -> None:
    output = tmp_path / "report.md"

    exit_code, _ = run(["--limit", "3", "--output", str(output)], _constant_handler)

    assert exit_code == 0
    report = output.read_text()
    assert "# Conversation evaluation" in report
    assert "- Run date (UTC):" in report
    assert "- Commit:" in report
    assert "## Summary by outcome" in report
    assert "## Summary by category and language" in report
    assert "## Latency" in report
    assert "- p50:" in report
    assert "- p95:" in report
    assert "## Per case" in report


def test_multi_turn_case_sends_the_first_turns_real_answer_as_history(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    output = tmp_path / "report.md"

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=ok_body(answer="The Economy limit is 7 kg."))
        return httpx.Response(200, json=ok_body(answer="Business is 10 kg."))

    exit_code, _ = run(["--case", "multi-policy-followup-en", "--output", str(output)], handler)

    assert exit_code in (0, 1)
    assert len(requests) == 2
    second_body: Any = json.loads(requests[1].content)
    assert second_body["history"][-1] == {
        "role": "assistant",
        "text": "The Economy limit is 7 kg.",
    }


def test_pacing_keeps_at_least_six_seconds_between_request_starts() -> None:
    exit_code, sleep = run(["--case", "multi-mixed-en"], _constant_handler)

    assert exit_code in (0, 1)
    assert len(sleep.calls) >= 2
    assert all(value >= 6.0 for value in sleep.calls)


def test_retry_after_seconds_header_is_honored_and_then_succeeds() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "12"}, json={"detail": "slow down"})
        return httpx.Response(200, json=ok_body())

    exit_code, sleep = run(["--case", "policy-cabin-economy-en"], handler)

    assert exit_code == 0
    assert calls == 2
    assert 12.0 in sleep.calls


def test_retry_after_http_date_header_is_parsed() -> None:
    calls = 0
    retry_at = email.utils.format_datetime(FIXED_NOW + timedelta(seconds=5))

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": retry_at}, json={})
        return httpx.Response(200, json=ok_body())

    exit_code, sleep = run(["--case", "policy-cabin-economy-en"], handler)

    assert exit_code == 0
    assert calls == 2
    assert any(value == pytest.approx(5.0, abs=1.0) for value in sleep.calls)


def test_missing_retry_after_header_falls_back_to_thirty_seconds() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=ok_body())

    exit_code, sleep = run(["--case", "policy-cabin-economy-en"], handler)

    assert exit_code == 0
    assert 30.0 in sleep.calls


def test_three_429s_exhaust_a_turn_and_trip_the_breaker_for_the_whole_run(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json={})

    exit_code, _ = run(["--limit", "2", "--output", str(output)], handler)

    assert exit_code == 1
    assert calls == 3
    report = output.read_text()
    assert "| 429 | 1 |" in report


def test_retry_after_over_the_cap_gives_up_immediately_and_trips_the_breaker() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "3600"}, json={})

    exit_code, sleep = run(["--limit", "2"], handler)

    assert exit_code == 1
    assert calls == 1
    assert sleep.calls == []


def test_three_503s_exhaust_only_that_case_and_the_run_continues() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        message = request_message(request)
        if "cabin baggage" in message.lower():
            return httpx.Response(503, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json=ok_body())

    exit_code, _ = run(["--limit", "2"], handler)

    assert exit_code == 0


def test_a_502_is_never_retried_and_bucketed_by_status(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, json={"detail": "bad gateway"})

    exit_code, _ = run(["--case", "policy-cabin-economy-en", "--output", str(output)], handler)

    assert exit_code == 0
    assert calls == 1
    report = output.read_text()
    assert "| 502 | 1 |" in report


def test_a_transport_error_lands_in_the_transport_bucket(tmp_path: Path) -> None:
    output = tmp_path / "report.md"

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    exit_code, _ = run(["--case", "policy-cabin-economy-en", "--output", str(output)], handler)

    assert exit_code == 0
    report = output.read_text()
    assert "| transport | 1 |" in report


def test_a_contract_failure_stops_the_case_without_sending_remaining_turns() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = ok_body()
        del body["flights_note"]
        return httpx.Response(200, json=body)

    exit_code, _ = run(["--case", "multi-policy-followup-en"], handler)

    assert exit_code == 0
    assert len(requests) == 1


def test_case_flag_sends_only_that_cases_turns() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=ok_body())

    run(["--case", "multi-mixed-en"], handler)

    assert len(requests) == 3


def test_case_and_limit_together_is_an_argparse_error() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--case", "x", "--limit", "1"])

    assert error.value.code == 2


def test_a_filtered_run_without_output_never_writes_the_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_output = tmp_path / "conversations.md"
    monkeypatch.setattr("evals.conversations.DEFAULT_OUTPUT", default_output)

    exit_code, _ = run(["--limit", "1"], _constant_handler)

    assert exit_code == 0
    assert not default_output.exists()
    out = capsys.readouterr().out
    assert "# Conversation evaluation" in out


def test_dry_run_never_builds_a_transport_and_lists_every_turn(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def exploding_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the dry run must never send a request")

    transport = httpx.MockTransport(exploding_handler)

    exit_code = main(["--dry-run"], transport=transport, now=fake_now)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "25 cases, 30 turns" in out
    assert "case policy-cabin-economy-en" in out


def test_dry_run_with_case_filter_shows_only_that_cases_turns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--dry-run", "--case", "multi-mixed-en"], now=fake_now)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.count("turn 0:") == 1
    assert out.count("turn 1:") == 1
    assert out.count("turn 2:") == 1


def test_model_flag_is_echoed_as_stated_by_operator(tmp_path: Path) -> None:
    output = tmp_path / "report.md"

    run(
        ["--case", "policy-cabin-economy-en", "--model", "gemini-3-flash", "--output", str(output)],
        _constant_handler,
    )

    assert "- Model: gemini-3-flash (stated by operator)" in output.read_text()


def test_model_flag_defaults_to_unknown(tmp_path: Path) -> None:
    output = tmp_path / "report.md"

    run(["--case", "policy-cabin-economy-en", "--output", str(output)], _constant_handler)

    assert "- Model: unknown (not reported by /chat)" in output.read_text()


def test_a_malformed_case_file_exits_one_with_the_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"not_cases": []}))
    monkeypatch.setattr("evals.conversations.DEFAULT_CASES_FILE", bad_file)

    exit_code = main([], transport=httpx.MockTransport(_constant_handler), now=fake_now)

    assert exit_code == 1
    assert "ValueError" in capsys.readouterr().err
