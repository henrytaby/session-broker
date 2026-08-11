from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.domain.ports.chrome_manager import IChromeInstanceManager

log = get_logger(__name__)


class ChromeWatchdog:
    """Background task that restarts headless Chrome instances that crash.
    Runs every 10s; the (blocking) health checks are short so they stay sync."""

    def __init__(self, manager: IChromeInstanceManager, interval: float = 10.0) -> None:
        self._manager = manager
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for info in self._manager.list_instances():
                    if not info.alive:
                        await asyncio.to_thread(self._manager.restart, info.name)
            except Exception as e:
                log.warning("[watchdog error] %r", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="chrome_watchdog")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
