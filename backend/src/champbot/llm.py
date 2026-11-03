from typing import Protocol


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...


class LLMError(Exception):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    def __init__(self, retry_after_seconds: int | None) -> None:
        super().__init__(f"Rate limited, retry_after_seconds={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


class LLMUnavailableError(LLMError):
    pass
