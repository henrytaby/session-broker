from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.core.logging import get_logger
from app.domain.exceptions import ChatNotReadyError

log = get_logger(__name__)

router = APIRouter()

_STATIC_DIR = Path(__file__).resolve().parents[4] / "static"


@router.get("/", response_class=HTMLResponse)
async def chat_page():
    """Serve the chat frontend at the root URL (per plan: GET / + WS /ws/gemini)."""
    index = _STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


@router.websocket("/ws/gemini")
async def ws_gemini(websocket: WebSocket):
    """WebSocket bridge: receive {prompt}, stream {type: chunk/complete/error}."""
    await websocket.accept()
    svc = getattr(websocket.app.state, "chat_service", None)
    if svc is None:
        await websocket.send_json(
            {"type": "error", "message": "Chat no disponible (--instances 0)."}
        )
        await websocket.close()
        return
    try:
        while True:
            data = await websocket.receive_json()
            prompt = data.get("prompt", "").strip()
            if not prompt:
                continue
            await websocket.send_json({"type": "thinking"})
            try:
                async for chunk in svc.send_prompt_and_stream(prompt):
                    await websocket.send_json({"type": "chunk", "html": chunk})
                await websocket.send_json({"type": "complete"})
            except ChatNotReadyError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.warning("ws/gemini error: %r", e)
                await websocket.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        log.info("ws/gemini cliente desconectado")
