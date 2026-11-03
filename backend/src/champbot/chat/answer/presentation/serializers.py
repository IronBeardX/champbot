from pydantic import BaseModel, Field, field_validator

MAX_MESSAGE_LENGTH = 2000


class ChatRequest(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_LENGTH)

    @field_validator("message")
    @classmethod
    def reject_blank(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("Message must not be blank")
        return message


class ChatResponse(BaseModel):
    answer: str
