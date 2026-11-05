from dataclasses import dataclass
from typing import Protocol

from champbot.common.core.domain.exceptions import ChampBotError


@dataclass(frozen=True)
class Chunk:
    id: str
    vector: list[float]
    metadata: dict[str, str]


class VectorStore(Protocol):
    async def upsert(self, chunks: list[Chunk]) -> list[str]: ...


class VectorStoreError(ChampBotError):
    pass
