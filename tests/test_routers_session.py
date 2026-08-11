from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.application.services.chat_service import ChatService
from app.application.services.lock_service import LockService
from app.application.services.session_service import SessionService
from app.domain.models import Fingerprint, LockResult, UnlockResult
from app.infrastructure.api.server import create_app
from app.infrastructure.chat.gemini_cdp_session import FakeAISession


def _fp() -> Fingerprint:
    return Fingerprint(
        user_agent="UA-test",
        platform="Win32",
        languages=["es-419", "es", "en"],
        timezone="America/La_Paz",
        locale="es-419",
        screen_width=1920,
        screen_height=1080,
        color_depth=24,
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE test",
        sec_ch_ua='"Chromium";v="140"',
    )


def _build_app():
    cookie_repo = MagicMock()
    profile_repo = MagicMock()
    fingerprint_provider = MagicMock()
    session_lock = AsyncMock()
    chrome_manager = MagicMock()
    ai_session = FakeAISession(["respuesta-1", "respuesta-2"])

    cookie_repo.get_storage_state.return_value = MagicMock()
    fingerprint_provider.current.return_value = _fp()
    fingerprint_provider.refresh.return_value = _fp()
    profile_repo.get_zip_path.return_value = Path("profile.zip")
    chrome_manager.list_instances.return_value = []

    app = create_app(
        cookie_repo=cookie_repo,
        profile_repo=profile_repo,
        fingerprint_provider=fingerprint_provider,
        session_lock=session_lock,
        chrome_manager=chrome_manager,
        ai_session=ai_session,
        skip_chrome_launch=True,
    )
    return app, session_lock, cookie_repo


@pytest.fixture
def client():
    app, _, _ = _build_app()
    with TestClient(app) as c:
        yield c


def test_health_no_token_required(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "instances" in data


def test_storage_state_requires_token(client):
    resp = client.get("/storage_state")
    assert resp.status_code == 403


def test_storage_state_with_token_and_mocked_state(client, monkeypatch):
    from app.domain.models import StorageState

    app, _, cookie_repo = _build_app()
    state = StorageState(cookies=[])
    cookie_repo.get_storage_state.return_value = state
    cookie_repo.persist.return_value = None
    # SESSIONS_DIR is redirected to tmp by the autouse fixture, so state_file
    # does not exist -> SessionService.get_storage_state takes the refresh path
    # through the mocked cookie repo.
    with TestClient(app) as c:
        resp = c.get("/storage_state?token=gemini2024")
    assert resp.status_code == 200
    assert "cookies" in resp.json()


def test_lock_acquire_and_unlock():
    from app.infrastructure.lock.in_memory_lock import InMemorySessionLock

    cookie_repo = MagicMock()
    profile_repo = MagicMock()
    fingerprint_provider = MagicMock()
    fingerprint_provider.current.return_value = _fp()
    fingerprint_provider.refresh.return_value = _fp()
    chrome_manager = MagicMock()
    chrome_manager.list_instances.return_value = []
    real_lock = InMemorySessionLock(timeout_sec=60)

    app = create_app(
        cookie_repo=cookie_repo,
        profile_repo=profile_repo,
        fingerprint_provider=fingerprint_provider,
        session_lock=real_lock,
        chrome_manager=chrome_manager,
        ai_session=FakeAISession(),
        skip_chrome_launch=True,
    )
    with TestClient(app) as c:
        r = c.get("/lock?token=gemini2024&client=pc-a")
        assert r.status_code == 200
        d = r.json()
        assert d["locked"] is True
        assert d["client"] == "pc-a"

        r2 = c.get("/lock?token=gemini2024&client=pc-b")
        assert r2.json()["locked"] is False
        assert r2.json()["holder"] == "pc-a"

        r3 = c.get("/unlock?token=gemini2024&client=pc-a")
        assert r3.json()["unlocked"] is True


def test_fingerprint_endpoint(client):
    resp = client.get("/fingerprint?token=gemini2024")
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "Win32"
    assert data["timezone"] == "America/La_Paz"


def test_root_serves_chat_frontend(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "ws/gemini" in resp.text


def test_chat_websocket_streams_chunks(client):
    import asyncio

    app, _, _ = _build_app()
    with TestClient(app) as c:
        with c.websocket_connect("/ws/gemini") as ws:
            ws.send_json({"prompt": "hola"})
            chunks = []
            while True:
                msg = ws.receive_json()
                chunks.append(msg)
                if msg["type"] in ("complete", "error"):
                    break
        types = [m["type"] for m in chunks]
        assert "thinking" in types
        assert "chunk" in types
        assert types[-1] == "complete"
        bodies = [m["html"] for m in chunks if m["type"] == "chunk"]
        assert "respuesta-1" in bodies or "respuesta-2" in bodies


def test_invalid_token_rejected(client):
    resp = client.get("/storage_state?token=wrong")
    assert resp.status_code == 403
