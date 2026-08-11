from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from app.core.logging import get_logger
from app.domain.exceptions import ChatNotReadyError
from app.domain.ports.ai_session import IAISession

log = get_logger(__name__)


class ChatService:
    """Serializes concurrent prompts with an asyncio.Lock (one prompt at a time
    on the shared pc1 instance) and forwards the streamed response."""

    def __init__(self, session: IAISession) -> None:
        self._session = session
        self._mu = asyncio.Lock()

    @property
    def session(self) -> IAISession:
        return self._session

    def is_ready(self) -> bool:
        return self._session.is_ready()

    async def ensure_ready(self) -> None:
        if not self._session.is_ready():
            try:
                await self._session.initialize()
            except Exception as e:
                log.warning("chat session no pudo inicializar: %r", e)
                raise ChatNotReadyError(str(e)) from e

    async def send_prompt_and_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        async with self._mu:
            await self.ensure_ready()
            async for chunk in self._session.send_prompt_and_stream(prompt):
                yield chunk
