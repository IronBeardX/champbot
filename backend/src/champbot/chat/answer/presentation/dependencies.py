from fastapi import Request

from champbot.common.llm.domain.provider import LLMProvider
from champbot.common.llm.infrastructure.gemini import GeminiProvider
from champbot.common.llm.infrastructure.settings import load_gemini_settings


def get_llm_provider(request: Request) -> LLMProvider:
    settings = load_gemini_settings(request.scope.get("env"))
    return GeminiProvider(settings.api_key, settings.model)
