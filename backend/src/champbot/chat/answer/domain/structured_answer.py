from typing import Annotated, Any, Literal, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict

Intent = Literal["policy", "flight_search", "general"]


def reject_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("Text must not be blank")
    return text


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(strict=True)

    intent: Intent
    answer: Annotated[str, AfterValidator(reject_blank)]
    source_ids: list[int]


STRUCTURED_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(get_args(Intent))},
        "answer": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["intent", "answer", "source_ids"],
    "propertyOrdering": ["intent", "answer", "source_ids"],
}
