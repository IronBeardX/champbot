from datetime import date, datetime, timedelta, timezone

from champbot.chat.common.domain.flights_prompt import (
    FLIGHTS_AIRPORT,
    FLIGHTS_DATE_ROW,
    FLIGHTS_PROMPT,
)
from champbot.common.flights.domain.airports import AIRPORT_CITIES

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
