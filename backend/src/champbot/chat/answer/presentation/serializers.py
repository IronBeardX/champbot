from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from champbot.common.llm.domain.message import Message, Role

MAX_USER_TEXT_LENGTH = 2000
MAX_ASSISTANT_TEXT_LENGTH = 8000
MAX_HISTORY_ITEMS = 20
MAX_HISTORY_TEXT_LENGTH = 40_000


def reject_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("Text must not be blank")
    return text


UserText = Annotated[str, Field(max_length=MAX_USER_TEXT_LENGTH), AfterValidator(reject_blank)]
AssistantText = Annotated[
    str, Field(max_length=MAX_ASSISTANT_TEXT_LENGTH), AfterValidator(reject_blank)
]


class UserTurn(BaseModel):
    role: Literal["user"]
    text: UserText


class AssistantTurn(BaseModel):
    role: Literal["assistant"]
    text: AssistantText


Turn = Annotated[UserTurn | AssistantTurn, Field(discriminator="role")]


class ChatRequest(BaseModel):
    message: UserText
    history: Annotated[list[Turn], Field(max_length=MAX_HISTORY_ITEMS)] = []

    @field_validator("history")
    @classmethod
    def check_conversation_shape(
        cls, history: list[UserTurn | AssistantTurn]
    ) -> list[UserTurn | AssistantTurn]:
        for index, turn in enumerate(history):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if turn.role != expected_role:
                raise ValueError(
                    f"History item {index} must have role '{expected_role}': "
                    "turns alternate, starting with user"
                )
        if len(history) % 2:
            raise ValueError("History must end with an assistant turn")
        if sum(len(turn.text) for turn in history) > MAX_HISTORY_TEXT_LENGTH:
            raise ValueError(
                f"History texts must total at most {MAX_HISTORY_TEXT_LENGTH} characters"
            )
        return history

    def to_messages(self) -> list[Message]:
        return [
            *(Message(Role(turn.role), turn.text) for turn in self.history),
            Message(Role.USER, self.message),
        ]


class SourceResponse(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
