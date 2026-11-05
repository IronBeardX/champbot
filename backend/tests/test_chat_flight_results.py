import asyncio
from datetime import UTC, date, datetime

import pytest

from champbot.chat.answer.application.flight_results import (
    FlightReply,
    answer_flight_query,
    format_long_date,
    join_cities,
    render_flight_line,
    render_flights_prompt,
    today_in_ist,
    upcoming_week,
)
from champbot.chat.answer.domain.structured_answer import FlightQuery
from champbot.common.flights.domain.flight import Cabin, Flight


class FakeFlightSearch:
    def __init__(self, flights: list[Flight] | None = None) -> None:
        self.flights = flights if flights is not None else []
        self.calls: list[tuple[str, str, date]] = []

    async def search(self, origin: str, destination: str, departure_date: date) -> list[Flight]:
        self.calls.append((origin, destination, departure_date))
        return self.flights


def ai_111() -> Flight:
    return Flight(
        flight_number="AI 111",
        origin="DEL",
        destination="LHR",
        departure=datetime(2026, 11, 6, 13, 30),
        arrival=datetime(2026, 11, 6, 18, 20),
        fares={Cabin.ECONOMY: 48000, Cabin.BUSINESS: 180000},
    )


def ai_112_overnight() -> Flight:
    return Flight(
        flight_number="AI 112",
        origin="LHR",
        destination="DEL",
        departure=datetime(2026, 11, 6, 21, 0),
        arrival=datetime(2026, 11, 7, 10, 30),
        fares={Cabin.ECONOMY: 48000, Cabin.BUSINESS: 180000},
    )


def answer(
    lead_in: str, query: FlightQuery | None, search: FakeFlightSearch, today: date
) -> FlightReply:
    return asyncio.run(answer_flight_query(lead_in, query, search, today))


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


def test_complete_query_with_results_searches_and_appends_flights() -> None:
    search = FakeFlightSearch([ai_111()])
    query = FlightQuery(origin="DEL", destination="LHR", date=date(2026, 11, 6))

    reply = answer(
        "Flights from Delhi to London on Friday 6 November 2026:",
        query,
        search,
        date(2026, 11, 5),
    )

    assert search.calls == [("DEL", "LHR", date(2026, 11, 6))]
    assert reply.answer == (
        "Flights from Delhi to London on Friday 6 November 2026:\n\n"
        "AI 111: DEL 13:30 → LHR 18:20, Economy INR 48,000, Business INR 180,000\n\n"
        "This is a sample schedule for this demo, not live fares or availability. Times are "
        "local to each airport. For real flights and bookings, visit airindia.com."
    )
    assert reply.flights == [ai_111()]


def test_complete_query_with_no_results_returns_no_flights_text() -> None:
    search = FakeFlightSearch([])
    query = FlightQuery(origin="DEL", destination="LHR", date=date(2026, 11, 10))

    reply = answer(
        "Flights from Delhi to London on Tuesday 10 November 2026:",
        query,
        search,
        date(2026, 11, 5),
    )

    assert reply.answer == (
        "Flights from Delhi to London on Tuesday 10 November 2026:\n\n"
        "There are no flights from Delhi (DEL) to London (LHR) on Tuesday 10 November 2026 "
        "in this sample schedule."
    )
    assert reply.flights == []


def test_date_in_the_past_returns_date_passed_without_calling_search() -> None:
    search = FakeFlightSearch([ai_111()])
    query = FlightQuery(origin="DEL", destination="LHR", date=date(2026, 11, 4))

    reply = answer("lead-in", query, search, date(2026, 11, 5))

    assert reply.answer == (
        "lead-in\n\nWednesday 4 November 2026 has already passed. Please choose today, "
        "Thursday 5 November 2026, or a later date."
    )
    assert reply.flights == []
    assert search.calls == []


def test_date_today_calls_search() -> None:
    search = FakeFlightSearch([ai_111()])
    query = FlightQuery(origin="DEL", destination="LHR", date=date(2026, 11, 5))

    answer("lead-in", query, search, date(2026, 11, 5))

    assert search.calls == [("DEL", "LHR", date(2026, 11, 5))]


@pytest.mark.parametrize("slot", ["origin", "destination"])
def test_unsupported_slot_returns_covered_cities_without_calling_search(slot: str) -> None:
    search = FakeFlightSearch([ai_111()])
    fields = {"origin": "DEL", "destination": "LHR", "date": date(2026, 11, 6)}
    fields[slot] = "UNSUPPORTED"
    query = FlightQuery.model_validate(fields)

    reply = answer("lead-in", query, search, date(2026, 11, 5))

    assert "This sample schedule only covers" in reply.answer
    assert "Delhi (DEL)" in reply.answer
    assert "and Singapore (SIN)" in reply.answer
    assert reply.flights == []
    assert search.calls == []


def test_same_airport_returns_same_airport_text_without_calling_search() -> None:
    search = FakeFlightSearch([ai_111()])
    query = FlightQuery(origin="DEL", destination="DEL", date=date(2026, 11, 6))

    reply = answer("lead-in", query, search, date(2026, 11, 5))

    assert reply.answer == (
        "lead-in\n\nDeparture and destination are both Delhi (DEL). Please choose two "
        "different cities."
    )
    assert reply.flights == []
    assert search.calls == []


@pytest.mark.parametrize("missing", ["origin", "destination", "date"])
def test_incomplete_query_leaves_the_models_answer_unchanged(missing: str) -> None:
    search = FakeFlightSearch([ai_111()])
    fields: dict[str, object] = {"origin": "DEL", "destination": "LHR", "date": date(2026, 11, 6)}
    fields[missing] = None
    query = FlightQuery.model_validate(fields)

    reply = answer("Where would you like to fly from?", query, search, date(2026, 11, 5))

    assert reply.answer == "Where would you like to fly from?"
    assert reply.flights == []
    assert search.calls == []


def test_null_flight_query_leaves_the_models_answer_unchanged() -> None:
    search = FakeFlightSearch([ai_111()])

    reply = answer("Where would you like to fly from?", None, search, date(2026, 11, 5))

    assert reply.answer == "Where would you like to fly from?"
    assert reply.flights == []
    assert search.calls == []


def test_render_flight_line_has_thousands_separators_and_cabin_order() -> None:
    assert render_flight_line(ai_111()) == (
        "AI 111: DEL 13:30 → LHR 18:20, Economy INR 48,000, Business INR 180,000"
    )


def test_render_flight_line_marks_an_overnight_arrival() -> None:
    assert render_flight_line(ai_112_overnight()) == (
        "AI 112: LHR 21:00 → DEL 10:30 (+1 day), Economy INR 48,000, Business INR 180,000"
    )


def test_render_flight_line_stays_well_under_the_history_budget() -> None:
    assert len(render_flight_line(ai_111())) < 100


def test_join_cities_lists_all_ten_in_catalog_order_with_and_before_the_last() -> None:
    assert join_cities() == (
        "Delhi (DEL), Mumbai (BOM), Bengaluru (BLR), Chennai (MAA), Kolkata (CCU), "
        "Hyderabad (HYD), Dubai (DXB), London (LHR), New York (JFK) and Singapore (SIN)"
    )
