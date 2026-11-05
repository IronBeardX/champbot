from typing import Annotated

from fastapi import APIRouter, Depends, Query

from champbot.common.flights.domain.search import FlightSearch
from champbot.common.flights.presentation.dependencies import get_flight_search
from champbot.common.flights.presentation.serializers import FlightResponse, FlightSearchQuery

router = APIRouter()


@router.get("/flights")
async def search_flights(
    query: Annotated[FlightSearchQuery, Query()],
    search: Annotated[FlightSearch, Depends(get_flight_search)],
) -> list[FlightResponse]:
    flights = await search.search(query.origin, query.destination, query.date)
    return [FlightResponse.from_flight(flight) for flight in flights]
