from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

AirportCode = Literal["DEL", "BOM", "BLR", "MAA", "CCU", "HYD", "DXB", "LHR", "JFK", "SIN"]

AIRPORT_CITIES: Mapping[AirportCode, str] = MappingProxyType(
    {
        "DEL": "Delhi",
        "BOM": "Mumbai",
        "BLR": "Bengaluru",
        "MAA": "Chennai",
        "CCU": "Kolkata",
        "HYD": "Hyderabad",
        "DXB": "Dubai",
        "LHR": "London",
        "JFK": "New York",
        "SIN": "Singapore",
    }
)
