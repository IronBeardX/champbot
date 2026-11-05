import json
from typing import get_args

import pytest
from pydantic import ValidationError

from champbot.chat.answer.domain.structured_answer import (
    STRUCTURED_ANSWER_SCHEMA,
    Intent,
    StructuredAnswer,
)


def test_parses_a_valid_payload() -> None:
    answer = StructuredAnswer.model_validate_json(
        '{"intent": "policy", "answer": "Economy gets 23kg.", "source_ids": [1, 2]}'
    )

    assert answer.intent == "policy"
    assert answer.answer == "Economy gets 23kg."
    assert answer.source_ids == [1, 2]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            '{"intent": "urgent", "answer": "Hi", "source_ids": []}', id="unknown-intent"
        ),
        pytest.param('{"answer": "Hi", "source_ids": []}', id="missing-intent"),
        pytest.param(
            '{"intent": "general", "answer": "  ", "source_ids": []}', id="blank-answer"
        ),
        pytest.param(
            '{"intent": "general", "answer": "Hi", "source_ids": ["1"]}', id="string-source-id"
        ),
        pytest.param(
            '{"intent": "general", "answer": "Hi", "source_ids": [true]}', id="bool-source-id"
        ),
        pytest.param(
            '{"intent": "general", "answer": "Hi", "source_ids": "1"}', id="source-ids-not-a-list"
        ),
        pytest.param("not json", id="invalid-json"),
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


def test_schema_has_no_refs_or_defs() -> None:
    serialized = str(STRUCTURED_ANSWER_SCHEMA)

    assert "$ref" not in serialized
    assert "$defs" not in serialized


def test_schema_has_no_max_output_tokens_knob() -> None:
    assert "maxOutputTokens" not in json.dumps(STRUCTURED_ANSWER_SCHEMA)
