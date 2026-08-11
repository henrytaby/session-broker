from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class IProfileRepository(ABC):
    """Builds the compressed profile.zip from the master profile."""

    @abstractmethod
    def build_zip(self) -> Path:
        ...

    @abstractmethod
    def get_zip_path(self) -> Path:
        ...
