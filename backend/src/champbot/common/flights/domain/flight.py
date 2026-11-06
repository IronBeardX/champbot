from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Cabin(StrEnum):
    ECONOMY = "economy"
    BUSINESS = "business"


@dataclass(frozen=True)
class Flight:
    flight_number: str
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration: timedelta
    fares: Mapping[Cabin, int]
