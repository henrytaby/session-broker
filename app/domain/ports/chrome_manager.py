from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import InstanceInfo


class IChromeInstanceManager(ABC):
    """Manages headless Chrome instances launched as subprocesses."""

    @abstractmethod
    def launch_all(self) -> None:
        ...

    @abstractmethod
    def launch(self, name: str) -> None:
        ...

    @abstractmethod
    def is_alive(self, chrome_port: int) -> bool:
        ...

    @abstractmethod
    def restart(self, name: str) -> bool:
        ...

    @abstractmethod
    def list_instances(self) -> list[InstanceInfo]:
        ...

    @abstractmethod
    def open_keepalive_page(self, chrome_port: int) -> bool:
        ...

    @abstractmethod
    def shutdown(self) -> None:
        ...
