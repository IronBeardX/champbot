from typing import Protocol

from champbot.common.core.domain.exceptions import ChampBotError
from champbot.common.llm.domain.message import Message


class LLMProvider(Protocol):
    async def generate(
        self, messages: list[Message], system_instruction: str | None = None
    ) -> str: ...


class LLMError(ChampBotError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    def __init__(self, retry_after_seconds: int | None) -> None:
        super().__init__(f"Rate limited, retry_after_seconds={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


class LLMUnavailableError(LLMError):
    pass
