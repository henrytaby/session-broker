from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import Fingerprint


class IFingerprintProvider(ABC):
    """Provides the current browser fingerprint."""

    @abstractmethod
    def current(self) -> Fingerprint:
        ...

    @abstractmethod
    def refresh(self) -> Fingerprint:
        ...
