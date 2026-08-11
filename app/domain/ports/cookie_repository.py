from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.models import StorageState


class ICookieRepository(ABC):
    """Decrypts Chrome cookies (DPAPI + AES-GCM) into a StorageState."""

    @abstractmethod
    def get_storage_state(self, profile_dir: Path) -> StorageState:
        ...

    @abstractmethod
    def persist(self, state: StorageState, out_path: Path) -> None:
        ...
