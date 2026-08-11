from __future__ import annotations

import asyncio

from app.application.services.session_service import SessionService
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class StorageStateWorker:
    """Background task that re-decrypts cookies on a fixed interval, capturing
    Google's renewed tokens. The DPAPI/SQLite work is blocking and runs in a
    thread via asyncio.to_thread."""

    def __init__(self, session_service: SessionService) -> None:
        self._service = session_service
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self._service.refresh_storage_state)
            except Exception as e:
                log.warning("[refresh error] %r", e)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.STORAGE_STATE_REFRESH_SEC
                )
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="storage_state_worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
