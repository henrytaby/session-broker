from __future__ import annotations

from app.domain.models import LockResult, UnlockResult
from app.domain.ports.session_lock import ISessionLock


class LockService:
    """Turn service wrapping ISessionLock (kept thin for testability/DI)."""

    def __init__(self, lock: ISessionLock) -> None:
        self._lock = lock

    async def acquire(self, client_id: str) -> LockResult:
        return await self._lock.acquire(client_id)

    async def release(self, client_id: str) -> UnlockResult:
        return await self._lock.release(client_id)

    async def status(self) -> LockResult:
        return await self._lock.status()
