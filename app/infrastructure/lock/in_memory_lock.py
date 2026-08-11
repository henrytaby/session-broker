from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.domain.models import LockResult, UnlockResult
from app.domain.ports.session_lock import ISessionLock


class InMemorySessionLock(ISessionLock):
    """ISessionLock impl: a single in-memory turn with an expiry timeout.

    Mirrors v9's `_session_lock` dict logic (holder + since) but async-safe.
    A holder expires after SESSION_LOCK_TIMEOUT_SEC; the same holder may renew.
    """

    def __init__(self, timeout_sec: int | None = None) -> None:
        self._timeout = timeout_sec if timeout_sec is not None else settings.SESSION_LOCK_TIMEOUT_SEC
        self._holder: str | None = None
        self._since: float = 0.0
        self._mu = asyncio.Lock()

    def _expired(self, now: float) -> bool:
        return self._holder is not None and (now - self._since) > self._timeout

    async def acquire(self, client_id: str) -> LockResult:
        now = time.time()
        async with self._mu:
            if self._holder is None or self._expired(now):
                self._holder = client_id
                self._since = now
                return LockResult(locked=True, client=client_id)
            if self._holder == client_id:
                self._since = now
                return LockResult(locked=True, client=client_id, renewed=True)
            remaining = int(self._timeout - (now - self._since))
            return LockResult(
                locked=False, holder=self._holder, remaining_sec=max(0, remaining)
            )

    async def release(self, client_id: str) -> UnlockResult:
        async with self._mu:
            if self._holder == client_id:
                self._holder = None
                self._since = 0.0
                return UnlockResult(unlocked=True)
            return UnlockResult(unlocked=False, holder=self._holder)

    async def status(self) -> LockResult:
        now = time.time()
        async with self._mu:
            if self._holder is None or self._expired(now):
                return LockResult(locked=False, holder=self._holder)
            remaining = int(self._timeout - (now - self._since))
            return LockResult(
                locked=True, holder=self._holder, remaining_sec=max(0, remaining)
            )
