import datetime as dt
from typing import Annotated, Any, Literal, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict

from champbot.common.flights.domain.airports import AirportCode

Intent = Literal["policy", "flight_search", "general"]

UNSUPPORTED = "UNSUPPORTED"
QueryAirport = Literal[AirportCode, "UNSUPPORTED"]


def reject_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("Text must not be blank")
    return text


class FlightQuery(BaseModel):
    model_config = ConfigDict(strict=True)

    origin: QueryAirport | None
    destination: QueryAirport | None
    date: dt.date | None


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(strict=True)

    intent: Intent
    flight_query: FlightQuery | None
    answer: Annotated[str, AfterValidator(reject_blank)]
    source_ids: list[int]


AIRPORT_ENUM: list[str] = list(get_args(QueryAirport))

_NULLABLE_AIRPORT: dict[str, Any] = {
    "anyOf": [{"type": "string", "enum": AIRPORT_ENUM}, {"type": "null"}]
}

FLIGHT_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "origin": _NULLABLE_AIRPORT,
        "destination": _NULLABLE_AIRPORT,
        "date": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]},
    },
    "required": ["origin", "destination", "date"],
    "propertyOrdering": ["origin", "destination", "date"],
}

STRUCTURED_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(get_args(Intent))},
        "flight_query": {"anyOf": [FLIGHT_QUERY_SCHEMA, {"type": "null"}]},
        "answer": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["intent", "flight_query", "answer", "source_ids"],
    "propertyOrdering": ["intent", "flight_query", "answer", "source_ids"],
}
