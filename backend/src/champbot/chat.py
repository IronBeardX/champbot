from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from champbot.common.llm.domain.provider import LLMProvider
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.common.llm.infrastructure.settings import load_gemini_settings

MAX_MESSAGE_LENGTH = 2000

router = APIRouter()


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


def get_llm_provider(request: Request) -> LLMProvider:
    settings = load_gemini_settings(request.scope.get("env"))
    return GeminiProvider(settings.api_key, settings.model)


@router.post("/chat")
async def chat(
    body: ChatRequest, provider: Annotated[LLMProvider, Depends(get_llm_provider)]
) -> ChatResponse:
    return ChatResponse(answer=await provider.generate(body.message))
