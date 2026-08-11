from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import LockResult, UnlockResult


class ISessionLock(ABC):
    """Turn-based lock to avoid simultaneous use from different IPs."""

    @abstractmethod
    async def acquire(self, client_id: str) -> LockResult:
        ...

    @abstractmethod
    async def release(self, client_id: str) -> UnlockResult:
        ...

    @abstractmethod
    async def status(self) -> LockResult:
        ...
