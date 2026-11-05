from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from champbot.chat.answer.domain.flight_replies import (
    COVERED_CITIES,
    DATE_PASSED,
    FARE,
    FLIGHT_LINE,
    NEXT_DAY_MARK,
    NO_FLIGHTS,
    SAME_AIRPORT,
    SAMPLE_SCHEDULE_NOTE,
)
from champbot.chat.answer.domain.structured_answer import UNSUPPORTED, FlightQuery
from champbot.chat.common.domain.flights_prompt import (
    FLIGHTS_AIRPORT,
    FLIGHTS_DATE_ROW,
    FLIGHTS_PROMPT,
)
from champbot.common.flights.domain.airports import AIRPORT_CITIES
from champbot.common.flights.domain.flight import Flight
from champbot.common.flights.domain.search import FlightSearch

IST = timezone(timedelta(hours=5, minutes=30), "IST")

_UPCOMING_WEEK_DAYS = 7


def today_in_ist(now: datetime) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be an aware datetime")
    return now.astimezone(IST).date()


def upcoming_week(today: date) -> list[date]:
    return [today + timedelta(days=offset) for offset in range(1, _UPCOMING_WEEK_DAYS + 1)]


def format_long_date(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B %Y}"


def render_flights_prompt(today: date) -> str:
    today_text = f"{format_long_date(today)} ({today.isoformat()})"
    date_table = "\n".join(
        FLIGHTS_DATE_ROW.format(weekday=day.strftime("%A"), iso_date=day.isoformat())
        for day in upcoming_week(today)
    )
    airports = ", ".join(
        FLIGHTS_AIRPORT.format(city=city, code=code) for code, city in AIRPORT_CITIES.items()
    )
    return FLIGHTS_PROMPT.format(today=today_text, date_table=date_table, airports=airports)


@dataclass(frozen=True)
class FlightReply:
    answer: str
    flights: list[Flight]


def join_cities() -> str:
    named = [f"{city} ({code})" for code, city in AIRPORT_CITIES.items()]
    return ", ".join(named[:-1]) + f" and {named[-1]}"


def render_flight_line(flight: Flight) -> str:
    fares = ", ".join(
        FARE.format(cabin=cabin.value.capitalize(), amount=amount)
        for cabin, amount in flight.fares.items()
    )
    next_day = NEXT_DAY_MARK if flight.arrival.date() > flight.departure.date() else ""
    return FLIGHT_LINE.format(
        flight_number=flight.flight_number,
        origin=flight.origin,
        departs=flight.departure.strftime("%H:%M"),
        destination=flight.destination,
        arrives=flight.arrival.strftime("%H:%M"),
        next_day=next_day,
        fares=fares,
    )


async def answer_flight_query(
    lead_in: str, query: FlightQuery | None, flight_search: FlightSearch, today: date
) -> FlightReply:
    if query is None:
        return FlightReply(lead_in, [])

    if query.origin == UNSUPPORTED or query.destination == UNSUPPORTED:
        return FlightReply(f"{lead_in}\n\n{COVERED_CITIES.format(cities=join_cities())}", [])

    if query.origin is None or query.destination is None or query.date is None:
        return FlightReply(lead_in, [])

    if query.origin == query.destination:
        text = SAME_AIRPORT.format(city=AIRPORT_CITIES[query.origin], code=query.origin)
        return FlightReply(f"{lead_in}\n\n{text}", [])

    if query.date < today:
        text = DATE_PASSED.format(date=format_long_date(query.date), today=format_long_date(today))
        return FlightReply(f"{lead_in}\n\n{text}", [])

    flights = await flight_search.search(query.origin, query.destination, query.date)
    if not flights:
        text = NO_FLIGHTS.format(
            origin_city=AIRPORT_CITIES[query.origin],
            origin=query.origin,
            destination_city=AIRPORT_CITIES[query.destination],
            destination=query.destination,
            date=format_long_date(query.date),
        )
        return FlightReply(f"{lead_in}\n\n{text}", [])

    lines = "\n".join(render_flight_line(flight) for flight in flights)
    return FlightReply(f"{lead_in}\n\n{lines}\n\n{SAMPLE_SCHEDULE_NOTE}", flights)
