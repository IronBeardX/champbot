import asyncio
from datetime import date, datetime, timedelta
from itertools import permutations

import pytest

from champbot.common.flights.domain.airports import AIRPORT_CITIES
from champbot.common.flights.domain.flight import Cabin, Flight
from champbot.common.flights.infrastructure.schedule_template import ScheduleTemplateFlightSearch

KNOWN_AIRPORTS = tuple(AIRPORT_CITIES)
A_FULL_WEEK = [date(2026, 11, 2) + timedelta(days=offset) for offset in range(7)]


def search(origin: str, destination: str, departure_date: date) -> list[Flight]:
    return asyncio.run(ScheduleTemplateFlightSearch().search(origin, destination, departure_date))


def test_served_route_on_a_served_weekday_returns_the_flight() -> None:
    monday = date(2026, 11, 9)

    flights = search("DEL", "LHR", monday)

    assert [flight.flight_number for flight in flights] == ["AI 111"]
    (flight,) = flights
    assert flight.departure == datetime(2026, 11, 9, 13, 30)
    assert flight.arrival == datetime(2026, 11, 9, 18, 20)
    assert set(flight.fares) == {Cabin.ECONOMY, Cabin.BUSINESS}


def test_served_route_on_an_unserved_weekday_returns_no_flights() -> None:
    tuesday = date(2026, 11, 10)

    assert search("DEL", "LHR", tuesday) == []


@pytest.mark.parametrize(
    ("origin", "destination"),
    [
        pytest.param("BLR", "JFK", id="well-formed-but-unserved-route"),
        pytest.param("DEL", "XYZ", id="outside-the-network"),
        pytest.param("DEL", "DEL", id="same-airport"),
    ],
)
def test_unserved_or_unknown_routes_return_no_flights(origin: str, destination: str) -> None:
    assert search(origin, destination, date(2026, 11, 9)) == []


def test_overnight_flight_arrives_the_next_calendar_day() -> None:
    monday = date(2026, 11, 9)

    (flight,) = search("LHR", "DEL", monday)

    assert flight.flight_number == "AI 112"
    assert flight.departure.date() == monday
    assert flight.arrival.date() == date(2026, 11, 10)


@pytest.mark.parametrize(
    "departure_date",
    [
        pytest.param(date(1999, 1, 4), id="far-past"),
        pytest.param(date(2099, 6, 1), id="far-future"),
    ],
)
def test_generation_works_for_any_date_not_just_a_fixed_range(departure_date: date) -> None:
    flights = search("DEL", "BOM", departure_date)

    assert [flight.flight_number for flight in flights] == ["AI 2401"]
    assert flights[0].departure.date() == departure_date


def test_date_max_does_not_raise_and_skips_the_overflowing_overnight_flight() -> None:
    assert date.max.weekday() in {0, 2, 4, 5}

    direct = search("DEL", "LHR", date.max)
    overnight_return = search("LHR", "DEL", date.max)

    assert [flight.flight_number for flight in direct] == ["AI 111"]
    assert overnight_return == []


def test_search_is_deterministic_across_calls() -> None:
    first = search("DEL", "LHR", date(2026, 11, 9))
    second = search("DEL", "LHR", date(2026, 11, 9))

    assert first == second


def test_fare_is_pinned_to_a_golden_value() -> None:
    (flight,) = search("DEL", "LHR", date(2026, 11, 9))

    assert flight.fares[Cabin.ECONOMY] == 48000
    assert flight.fares[Cabin.BUSINESS] == 180000


def test_fare_varies_across_dates_within_bounds_and_in_multiples_of_ten() -> None:
    base_economy = 5000
    fares: set[int] = set()
    for day_offset in range(30):
        departure_date = date(2026, 11, 1 + day_offset)
        (flight,) = search("DEL", "BOM", departure_date)
        economy_fare = flight.fares[Cabin.ECONOMY]
        assert base_economy * 0.80 <= economy_fare <= base_economy * 1.30
        assert economy_fare % 10 == 0
        fares.add(economy_fare)

    assert len(fares) >= 10


def all_flights_over_a_full_week() -> list[Flight]:
    return [
        flight
        for origin, destination in permutations(KNOWN_AIRPORTS, 2)
        for departure_date in A_FULL_WEEK
        for flight in search(origin, destination, departure_date)
    ]


def test_business_fare_is_always_above_economy_fare() -> None:
    flights = all_flights_over_a_full_week()

    assert flights
    for flight in flights:
        assert flight.fares[Cabin.BUSINESS] > flight.fares[Cabin.ECONOMY]


def test_schedule_is_internally_consistent() -> None:
    flights = all_flights_over_a_full_week()
    flight_number_routes: dict[str, tuple[str, str]] = {}
    routes: set[tuple[str, str]] = set()

    for flight in flights:
        route = (flight.origin, flight.destination)
        assert flight_number_routes.setdefault(flight.flight_number, route) == route
        routes.add(route)

    assert routes
    for origin, destination in routes:
        assert (destination, origin) in routes


def test_every_catalog_airport_is_served_as_origin_and_destination() -> None:
    flights = all_flights_over_a_full_week()

    origins = {flight.origin for flight in flights}
    destinations = {flight.destination for flight in flights}

    for code in KNOWN_AIRPORTS:
        assert code in origins
        assert code in destinations
