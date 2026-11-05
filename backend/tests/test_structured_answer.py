import datetime as dt
import json
from typing import get_args

import pytest
from pydantic import ValidationError

from champbot.chat.answer.domain.structured_answer import (
    FLIGHT_QUERY_SCHEMA,
    STRUCTURED_ANSWER_SCHEMA,
    FlightQuery,
    Intent,
    QueryAirport,
    StructuredAnswer,
)


def test_parses_a_valid_payload_with_no_flight_query() -> None:
    answer = StructuredAnswer.model_validate_json(
        '{"intent": "policy", "flight_query": null, "answer": "Economy gets 23kg.",'
        ' "source_ids": [1, 2]}'
    )

    assert answer.intent == "policy"
    assert answer.flight_query is None
    assert answer.answer == "Economy gets 23kg."
    assert answer.source_ids == [1, 2]


def test_parses_a_complete_flight_query() -> None:
    answer = StructuredAnswer.model_validate_json(
        '{"intent": "flight_search", "flight_query": '
        '{"origin": "DEL", "destination": "LHR", "date": "2026-11-06"}, '
        '"answer": "Looking for flights.", "source_ids": []}'
    )

    assert answer.flight_query == FlightQuery(
        origin="DEL", destination="LHR", date=dt.date(2026, 11, 6)
    )


def test_parses_a_flight_query_with_every_field_null() -> None:
    answer = StructuredAnswer.model_validate_json(
        '{"intent": "flight_search", "flight_query": '
        '{"origin": null, "destination": null, "date": null}, '
        '"answer": "Where would you like to fly from?", "source_ids": []}'
    )

    assert answer.flight_query == FlightQuery(origin=None, destination=None, date=None)


@pytest.mark.parametrize("slot", ["origin", "destination"])
def test_parses_unsupported_in_either_slot(slot: str) -> None:
    query: dict[str, object] = {"origin": None, "destination": None, "date": None}
    query[slot] = "UNSUPPORTED"
    payload = json.dumps(
        {
            "intent": "flight_search",
            "flight_query": query,
            "answer": "We don't fly there.",
            "source_ids": [],
        }
    )

    answer = StructuredAnswer.model_validate_json(payload)

    assert getattr(answer.flight_query, slot) == "UNSUPPORTED"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            '{"intent": "urgent", "flight_query": null, "answer": "Hi", "source_ids": []}',
            id="unknown-intent",
        ),
        pytest.param(
            '{"flight_query": null, "answer": "Hi", "source_ids": []}', id="missing-intent"
        ),
        pytest.param(
            '{"intent": "general", "flight_query": null, "answer": "  ", "source_ids": []}',
            id="blank-answer",
        ),
        pytest.param(
            '{"intent": "general", "flight_query": null, "answer": "Hi", "source_ids": ["1"]}',
            id="string-source-id",
        ),
        pytest.param(
            '{"intent": "general", "flight_query": null, "answer": "Hi", "source_ids": [true]}',
            id="bool-source-id",
        ),
        pytest.param(
            '{"intent": "general", "flight_query": null, "answer": "Hi", "source_ids": "1"}',
            id="source-ids-not-a-list",
        ),
        pytest.param("not json", id="invalid-json"),
        pytest.param(
            '{"intent": "general", "answer": "Hi", "source_ids": []}', id="missing-flight-query"
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": '
            '{"origin": "CDG", "destination": null, "date": null}, "answer": "Hi",'
            ' "source_ids": []}',
            id="airport-outside-the-enum",
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": '
            '{"origin": "del", "destination": null, "date": null}, "answer": "Hi",'
            ' "source_ids": []}',
            id="lowercase-airport",
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": '
            '{"origin": null, "destination": null, "date": "2026-02-30"}, "answer": "Hi",'
            ' "source_ids": []}',
            id="calendar-invalid-date",
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": '
            '{"origin": null, "destination": null, "date": "13/11/2026"}, "answer": "Hi",'
            ' "source_ids": []}',
            id="non-iso-date",
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": {"origin": null, "destination": null},'
            ' "answer": "Hi", "source_ids": []}',
            id="missing-nested-date-key",
        ),
        pytest.param(
            '{"intent": "flight_search", "flight_query": '
            '{"origin": null, "destination": null, "date": 20261106}, "answer": "Hi",'
            ' "source_ids": []}',
            id="non-string-date",
        ),
    ],
)
def test_rejects_an_invalid_payload(payload: str) -> None:
    with pytest.raises(ValidationError):
        StructuredAnswer.model_validate_json(payload)


def test_schema_fields_match_the_model_fields_in_order() -> None:
    field_names = list(StructuredAnswer.model_fields)

    assert STRUCTURED_ANSWER_SCHEMA["required"] == field_names
    assert STRUCTURED_ANSWER_SCHEMA["propertyOrdering"] == field_names
    assert list(STRUCTURED_ANSWER_SCHEMA["properties"]) == field_names


def test_schema_intent_enum_matches_the_intent_literal() -> None:
    assert STRUCTURED_ANSWER_SCHEMA["properties"]["intent"]["enum"] == list(get_args(Intent))


def test_nested_flight_query_schema_fields_match_the_model_fields_in_order() -> None:
    field_names = list(FlightQuery.model_fields)

    assert FLIGHT_QUERY_SCHEMA["required"] == field_names
    assert FLIGHT_QUERY_SCHEMA["propertyOrdering"] == field_names
    assert list(FLIGHT_QUERY_SCHEMA["properties"]) == field_names


def test_airport_enum_is_the_catalog_plus_unsupported() -> None:
    enum = FLIGHT_QUERY_SCHEMA["properties"]["origin"]["anyOf"][0]["enum"]

    assert enum == list(get_args(QueryAirport))
    assert enum[-1] == "UNSUPPORTED"


def test_schema_has_no_refs_or_defs() -> None:
    serialized = str(STRUCTURED_ANSWER_SCHEMA)

    assert "$ref" not in serialized
    assert "$defs" not in serialized


def test_schema_has_no_max_output_tokens_knob() -> None:
    assert "maxOutputTokens" not in json.dumps(STRUCTURED_ANSWER_SCHEMA)
