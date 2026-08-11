from __future__ import annotations

from fastapi import Request

from app.application.services.chat_service import ChatService
from app.application.services.lock_service import LockService
from app.application.services.session_service import SessionService
from app.domain.ports.chrome_manager import IChromeInstanceManager


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_lock_service(request: Request) -> LockService:
    return request.app.state.lock_service


def get_chat_service(request: Request) -> ChatService | None:
    return getattr(request.app.state, "chat_service", None)


def get_chrome_manager(request: Request) -> IChromeInstanceManager | None:
    return getattr(request.app.state, "chrome_manager", None)
