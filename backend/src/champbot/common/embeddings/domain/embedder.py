from typing import Protocol

from champbot.common.core.domain.exceptions import ChampBotError


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingError(ChampBotError):
    pass


class EmbeddingTimeoutError(EmbeddingError):
    pass
