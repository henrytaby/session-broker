from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class IAISession(ABC):
    """Contract for an AI chat session (preserved from gemini-proxy)."""

    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def send_prompt_and_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        yield ""

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        ...
