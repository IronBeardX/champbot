import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from champbot.common.flights.domain.flight import Cabin, Flight

_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_iso_date(value: object) -> object:
    if isinstance(value, str) and not _ISO_DATE_PATTERN.fullmatch(value):
        raise ValueError("Date must be in YYYY-MM-DD format")
    return value


AirportCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
IsoDate = Annotated[date, BeforeValidator(require_iso_date)]


class FlightSearchQuery(BaseModel):
    origin: AirportCode
    destination: AirportCode
    date: IsoDate


class FlightResponse(BaseModel):
    flight_number: str
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration_minutes: int
    fares: dict[Cabin, int]
    currency: Literal["INR"] = "INR"

    @classmethod
    def from_flight(cls, flight: Flight) -> "FlightResponse":
        return cls(
            flight_number=flight.flight_number,
            origin=flight.origin,
            destination=flight.destination,
            departure=flight.departure,
            arrival=flight.arrival,
            duration_minutes=int(flight.duration.total_seconds() // 60),
            fares=dict(flight.fares),
        )
