from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.application.services.chat_service import ChatService
from app.application.services.lock_service import LockService
from app.application.services.session_service import SessionService
from app.application.workers.chrome_watchdog import ChromeWatchdog
from app.application.workers.storage_state_worker import StorageStateWorker
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.domain.ports.chrome_manager import IChromeInstanceManager
from app.domain.ports.cookie_repository import ICookieRepository
from app.domain.ports.fingerprint_provider import IFingerprintProvider
from app.domain.ports.profile_repository import IProfileRepository
from app.domain.ports.session_lock import ISessionLock
from app.infrastructure.api.routers import chat as chat_router
from app.infrastructure.api.routers import session as session_router

log = get_logger(__name__)


def create_app(
    *,
    cookie_repo: ICookieRepository | None = None,
    profile_repo: IProfileRepository | None = None,
    fingerprint_provider: IFingerprintProvider | None = None,
    session_lock: ISessionLock | None = None,
    chrome_manager: IChromeInstanceManager | None = None,
    ai_session=None,
    skip_chrome_launch: bool = False,
) -> FastAPI:
    """FastAPI app factory.

    Dependencies default to None so tests can inject fakes. When None, the
    composition root wires the real adapters. `skip_chrome_launch` is used in
    tests / --instances 0 mode to avoid spawning subprocesses.
    """
    from app.composition.root import build_default_adapters

    if cookie_repo is None or profile_repo is None or fingerprint_provider is None:
        adapters = build_default_adapters(
            chrome_manager=chrome_manager,
            cookie_repo=cookie_repo,
            profile_repo=profile_repo,
            fingerprint_provider=fingerprint_provider,
            session_lock=session_lock,
        )
        cookie_repo = adapters["cookie_repo"]
        profile_repo = adapters["profile_repo"]
        fingerprint_provider = adapters["fingerprint_provider"]
        session_lock = adapters["session_lock"]
        if chrome_manager is None:
            chrome_manager = adapters["chrome_manager"]

    setup_logging()

    session_service = SessionService(cookie_repo, profile_repo, fingerprint_provider)
    lock_service = LockService(session_lock)

    chat_service = None
    if ai_session is not None:
        chat_service = ChatService(ai_session)

    storage_worker = StorageStateWorker(session_service)
    watchdog = ChromeWatchdog(chrome_manager) if chrome_manager is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("iniciando servidor (instancias=%d)", settings.CHROME_INSTANCES)
        try:
            fingerprint_provider.refresh()
        except Exception as e:
            log.warning("fingerprint refresh falló: %r", e)
        try:
            session_service.refresh_storage_state()
        except Exception as e:
            log.warning("storage_state inicial falló: %r", e)

        if not skip_chrome_launch and chrome_manager is not None and settings.CHROME_INSTANCES > 0:
            try:
                chrome_manager.launch_all()
            except Exception as e:
                log.warning("chrome launch falló: %r", e)

        storage_worker.start()
        if watchdog is not None and settings.CHROME_INSTANCES > 0:
            watchdog.start()

        if chat_service is not None and settings.CHROME_INSTANCES > 0:
            try:
                await chat_service.ensure_ready()
            except Exception as e:
                log.warning("chat session no pudo inicializar al arranque: %r", e)

        try:
            yield
        finally:
            await storage_worker.stop()
            if watchdog is not None:
                await watchdog.stop()
            if chat_service is not None:
                await chat_service.session.close()
            if chrome_manager is not None:
                chrome_manager.shutdown()

    app = FastAPI(title="Session Sharing Server", lifespan=lifespan)
    app.state.session_service = session_service
    app.state.lock_service = lock_service
    app.state.chrome_manager = chrome_manager
    app.state.chat_service = chat_service

    app.include_router(session_router.router)
    app.include_router(chat_router.router)
    return app
