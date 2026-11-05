from datetime import date
from typing import Protocol

from champbot.common.flights.domain.flight import Flight


class FlightSearch(Protocol):
    async def search(
        self, origin: str, destination: str, departure_date: date
    ) -> list[Flight]: ...
