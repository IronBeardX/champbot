import hashlib
from calendar import FRIDAY, MONDAY, SATURDAY, SUNDAY, THURSDAY, TUESDAY, WEDNESDAY
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from champbot.common.flights.domain.airports import AirportCode
from champbot.common.flights.domain.flight import Cabin, Flight

_DAILY = frozenset(range(7))
_FARE_PCT_MIN = 80
_FARE_PCT_RANGE = 51

_STANDARD_UTC_OFFSETS: Mapping[AirportCode, timedelta] = {
    "DEL": timedelta(hours=5, minutes=30),
    "BOM": timedelta(hours=5, minutes=30),
    "BLR": timedelta(hours=5, minutes=30),
    "MAA": timedelta(hours=5, minutes=30),
    "CCU": timedelta(hours=5, minutes=30),
    "HYD": timedelta(hours=5, minutes=30),
    "DXB": timedelta(hours=4),
    "LHR": timedelta(hours=0),
    "JFK": timedelta(hours=-5),
    "SIN": timedelta(hours=8),
}


@dataclass(frozen=True)
class _ScheduledFlight:
    flight_number: str
    origin: AirportCode
    destination: AirportCode
    departs: time
    arrives: time
    arrival_day_offset: int
    weekdays: frozenset[int]
    base_fares: Mapping[Cabin, int]


_SCHEDULE: tuple[_ScheduledFlight, ...] = (
    _ScheduledFlight(
        "AI 2401",
        "DEL",
        "BOM",
        time(7, 0),
        time(9, 10),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5000, Cabin.BUSINESS: 18000},
    ),
    _ScheduledFlight(
        "AI 2402",
        "BOM",
        "DEL",
        time(10, 30),
        time(12, 40),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5000, Cabin.BUSINESS: 18000},
    ),
    _ScheduledFlight(
        "AI 2403",
        "DEL",
        "BLR",
        time(8, 15),
        time(11, 0),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5500, Cabin.BUSINESS: 19000},
    ),
    _ScheduledFlight(
        "AI 2404",
        "BLR",
        "DEL",
        time(12, 20),
        time(15, 5),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5500, Cabin.BUSINESS: 19000},
    ),
    _ScheduledFlight(
        "AI 2405",
        "DEL",
        "MAA",
        time(9, 0),
        time(11, 50),
        0,
        _DAILY,
        {Cabin.ECONOMY: 6000, Cabin.BUSINESS: 20000},
    ),
    _ScheduledFlight(
        "AI 2406",
        "MAA",
        "DEL",
        time(13, 0),
        time(15, 50),
        0,
        _DAILY,
        {Cabin.ECONOMY: 6000, Cabin.BUSINESS: 20000},
    ),
    _ScheduledFlight(
        "AI 2407",
        "DEL",
        "CCU",
        time(6, 30),
        time(8, 40),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5200, Cabin.BUSINESS: 18500},
    ),
    _ScheduledFlight(
        "AI 2408",
        "CCU",
        "DEL",
        time(10, 0),
        time(12, 15),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5200, Cabin.BUSINESS: 18500},
    ),
    _ScheduledFlight(
        "AI 2409",
        "DEL",
        "HYD",
        time(13, 0),
        time(15, 15),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5800, Cabin.BUSINESS: 19500},
    ),
    _ScheduledFlight(
        "AI 2410",
        "HYD",
        "DEL",
        time(16, 30),
        time(18, 45),
        0,
        _DAILY,
        {Cabin.ECONOMY: 5800, Cabin.BUSINESS: 19500},
    ),
    _ScheduledFlight(
        "AI 2411",
        "BOM",
        "BLR",
        time(8, 0),
        time(9, 45),
        0,
        _DAILY,
        {Cabin.ECONOMY: 6500, Cabin.BUSINESS: 21000},
    ),
    _ScheduledFlight(
        "AI 2412",
        "BLR",
        "BOM",
        time(11, 0),
        time(12, 45),
        0,
        _DAILY,
        {Cabin.ECONOMY: 6500, Cabin.BUSINESS: 21000},
    ),
    _ScheduledFlight(
        "AI 2413",
        "BOM",
        "HYD",
        time(18, 0),
        time(19, 30),
        0,
        _DAILY,
        {Cabin.ECONOMY: 7000, Cabin.BUSINESS: 22000},
    ),
    _ScheduledFlight(
        "AI 2414",
        "HYD",
        "BOM",
        time(20, 30),
        time(22, 0),
        0,
        _DAILY,
        {Cabin.ECONOMY: 7000, Cabin.BUSINESS: 22000},
    ),
    _ScheduledFlight(
        "AI 995",
        "DEL",
        "DXB",
        time(20, 30),
        time(22, 45),
        0,
        _DAILY,
        {Cabin.ECONOMY: 14000, Cabin.BUSINESS: 45000},
    ),
    _ScheduledFlight(
        "AI 996",
        "DXB",
        "DEL",
        time(23, 45),
        time(4, 15),
        1,
        _DAILY,
        {Cabin.ECONOMY: 14000, Cabin.BUSINESS: 45000},
    ),
    _ScheduledFlight(
        "AI 983",
        "BOM",
        "DXB",
        time(19, 0),
        time(20, 45),
        0,
        _DAILY,
        {Cabin.ECONOMY: 14500, Cabin.BUSINESS: 46000},
    ),
    _ScheduledFlight(
        "AI 984",
        "DXB",
        "BOM",
        time(22, 0),
        time(2, 45),
        1,
        _DAILY,
        {Cabin.ECONOMY: 14500, Cabin.BUSINESS: 46000},
    ),
    _ScheduledFlight(
        "AI 111",
        "DEL",
        "LHR",
        time(13, 30),
        time(18, 20),
        0,
        frozenset({MONDAY, WEDNESDAY, FRIDAY, SATURDAY}),
        {Cabin.ECONOMY: 48000, Cabin.BUSINESS: 180000},
    ),
    _ScheduledFlight(
        "AI 112",
        "LHR",
        "DEL",
        time(21, 0),
        time(10, 30),
        1,
        frozenset({MONDAY, WEDNESDAY, FRIDAY, SATURDAY}),
        {Cabin.ECONOMY: 48000, Cabin.BUSINESS: 180000},
    ),
    _ScheduledFlight(
        "AI 101",
        "DEL",
        "JFK",
        time(2, 0),
        time(7, 30),
        0,
        frozenset({TUESDAY, THURSDAY, SATURDAY, SUNDAY}),
        {Cabin.ECONOMY: 62000, Cabin.BUSINESS: 230000},
    ),
    _ScheduledFlight(
        "AI 102",
        "JFK",
        "DEL",
        time(11, 0),
        time(11, 30),
        1,
        frozenset({TUESDAY, THURSDAY, SATURDAY, SUNDAY}),
        {Cabin.ECONOMY: 62000, Cabin.BUSINESS: 230000},
    ),
    _ScheduledFlight(
        "AI 380",
        "DEL",
        "SIN",
        time(23, 0),
        time(7, 15),
        1,
        frozenset({MONDAY, THURSDAY, SATURDAY}),
        {Cabin.ECONOMY: 22000, Cabin.BUSINESS: 75000},
    ),
    _ScheduledFlight(
        "AI 381",
        "SIN",
        "DEL",
        time(8, 45),
        time(12, 0),
        0,
        frozenset({MONDAY, THURSDAY, SATURDAY}),
        {Cabin.ECONOMY: 22000, Cabin.BUSINESS: 75000},
    ),
)


def _fare_multiplier_pct(flight_number: str, departure_date: date) -> int:
    key = f"{flight_number}|{departure_date.isoformat()}"
    digest = hashlib.sha256(key.encode()).digest()
    return _FARE_PCT_MIN + int.from_bytes(digest[:2], "big") % _FARE_PCT_RANGE


def _fare(base: int, pct: int) -> int:
    return (base * pct + 500) // 1000 * 10


def _fares_for(base_fares: Mapping[Cabin, int], pct: int) -> dict[Cabin, int]:
    return {cabin: _fare(base, pct) for cabin, base in base_fares.items()}


class ScheduleTemplateFlightSearch:
    async def search(self, origin: str, destination: str, departure_date: date) -> list[Flight]:
        flights: list[Flight] = []
        for scheduled in _SCHEDULE:
            if scheduled.origin != origin or scheduled.destination != destination:
                continue
            if departure_date.weekday() not in scheduled.weekdays:
                continue
            flight = _build_flight(scheduled, departure_date)
            if flight is not None:
                flights.append(flight)
        return sorted(flights, key=lambda flight: flight.departure)


def _build_flight(scheduled: _ScheduledFlight, departure_date: date) -> Flight | None:
    departure = datetime.combine(departure_date, scheduled.departs)
    try:
        arrival_date = departure_date + timedelta(days=scheduled.arrival_day_offset)
    except OverflowError:
        return None
    arrival = datetime.combine(arrival_date, scheduled.arrives)
    duration = (arrival - _STANDARD_UTC_OFFSETS[scheduled.destination]) - (
        departure - _STANDARD_UTC_OFFSETS[scheduled.origin]
    )
    pct = _fare_multiplier_pct(scheduled.flight_number, departure_date)
    return Flight(
        flight_number=scheduled.flight_number,
        origin=scheduled.origin,
        destination=scheduled.destination,
        departure=departure,
        arrival=arrival,
        duration=duration,
        fares=_fares_for(scheduled.base_fares, pct),
    )
