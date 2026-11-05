from typing import Annotated

from fastapi import APIRouter, Depends

from champbot.chat.answer.application.services import answer_chat
from champbot.chat.answer.presentation.dependencies import (
    RetrievalPorts,
    get_llm_provider,
    get_min_score,
    get_retrieval_ports,
)
from champbot.chat.answer.presentation.serializers import ChatRequest, ChatResponse, SourceResponse
from champbot.common.llm.domain.provider import LLMProvider

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    ports: Annotated[RetrievalPorts, Depends(get_retrieval_ports)],
    min_score: Annotated[float, Depends(get_min_score)],
) -> ChatResponse:
    result = await answer_chat(
        body.to_messages(),
        provider,
        ports.embedder,
        ports.vector_store,
        min_score=min_score,
    )
    return ChatResponse(
        intent=result.intent,
        answer=result.answer,
        sources=[SourceResponse(title=source.title, url=source.url) for source in result.sources],
    )
