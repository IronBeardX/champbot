from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    role: Role
    text: str
