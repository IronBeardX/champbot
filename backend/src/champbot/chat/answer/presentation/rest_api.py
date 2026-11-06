from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from champbot.chat.answer.application.services import answer_chat
from champbot.chat.answer.presentation.dependencies import (
    RetrievalPorts,
    get_llm_provider,
    get_min_score,
    get_retrieval_ports,
    get_today,
)
from champbot.chat.answer.presentation.serializers import ChatRequest, ChatResponse, SourceResponse
from champbot.common.flights.domain.search import FlightSearch
from champbot.common.flights.presentation.dependencies import get_flight_search
from champbot.common.flights.presentation.serializers import FlightResponse
from champbot.common.llm.domain.provider import LLMProvider

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    ports: Annotated[RetrievalPorts, Depends(get_retrieval_ports)],
    flight_search: Annotated[FlightSearch, Depends(get_flight_search)],
    min_score: Annotated[float, Depends(get_min_score)],
    today: Annotated[date, Depends(get_today)],
) -> ChatResponse:
    result = await answer_chat(
        body.to_messages(),
        provider,
        ports.embedder,
        ports.vector_store,
        flight_search=flight_search,
        min_score=min_score,
        today=today,
    )
    return ChatResponse(
        intent=result.intent,
        answer=result.answer,
        sources=[SourceResponse(title=source.title, url=source.url) for source in result.sources],
        flights=[FlightResponse.from_flight(flight) for flight in result.flights],
        flights_note=result.flights_note,
    )
