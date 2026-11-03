from typing import Protocol

from champbot.common.core.domain.exceptions import ChampBotError


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...


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
