from datetime import UTC, date, datetime

import pytest

from champbot.chat.answer.application.flight_results import (
    format_long_date,
    render_flights_prompt,
    today_in_ist,
    upcoming_week,
)


def test_today_in_ist_just_before_midnight_ist_is_still_the_same_day() -> None:
    now = datetime(2026, 11, 5, 18, 29, 59, tzinfo=UTC)

    assert today_in_ist(now) == date(2026, 11, 5)


def test_today_in_ist_rolls_over_at_ist_midnight() -> None:
    now = datetime(2026, 11, 5, 18, 30, 0, tzinfo=UTC)

    assert today_in_ist(now) == date(2026, 11, 6)


def test_today_in_ist_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        today_in_ist(datetime(2026, 11, 5, 12, 0, 0))


def test_upcoming_week_starts_tomorrow_and_covers_seven_days() -> None:
    today = date(2026, 11, 5)

    week = upcoming_week(today)

    assert week == [date(2026, 11, day) for day in range(6, 13)]


def test_upcoming_week_has_every_weekday_exactly_once() -> None:
    week = upcoming_week(date(2026, 11, 5))

    assert sorted(day.weekday() for day in week) == list(range(7))


def test_upcoming_week_crosses_a_year_boundary() -> None:
    week = upcoming_week(date(2026, 12, 28))

    assert week == [
        date(2026, 12, 29),
        date(2026, 12, 30),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
        date(2027, 1, 3),
        date(2027, 1, 4),
    ]


def test_format_long_date_has_no_leading_zero_on_the_day() -> None:
    assert format_long_date(date(2026, 11, 6)) == "Friday 6 November 2026"


def test_render_flights_prompt_contains_both_forms_of_today() -> None:
    prompt = render_flights_prompt(date(2026, 11, 5))

    assert "Thursday 5 November 2026" in prompt
    assert "2026-11-05" in prompt


def test_render_flights_prompt_contains_every_table_row() -> None:
    prompt = render_flights_prompt(date(2026, 11, 5))

    assert "- Friday: 2026-11-06" in prompt
    assert "- Thursday: 2026-11-12" in prompt


def test_render_flights_prompt_contains_every_airport() -> None:
    prompt = render_flights_prompt(date(2026, 11, 5))

    assert "Delhi DEL" in prompt
    assert "Singapore SIN" in prompt


def test_render_flights_prompt_leaves_no_placeholder_unfilled() -> None:
    prompt = render_flights_prompt(date(2026, 11, 5))

    assert "{" not in prompt
