from typing import Annotated

from fastapi import APIRouter, Depends

from champbot.chat.answer.presentation.dependencies import get_llm_provider, get_system_instruction
from champbot.chat.answer.presentation.serializers import ChatRequest, ChatResponse
from champbot.common.llm.domain.provider import LLMProvider

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    system_instruction: Annotated[str, Depends(get_system_instruction)],
) -> ChatResponse:
    return ChatResponse(answer=await provider.generate(body.to_messages(), system_instruction))
