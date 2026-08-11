from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse

from app.application.services.lock_service import LockService
from app.application.services.session_service import SessionService
from app.core.logging import get_logger
from app.domain.ports.chrome_manager import IChromeInstanceManager
from app.infrastructure.api.auth import require_token
from app.infrastructure.api.deps import (
    get_chrome_manager,
    get_lock_service,
    get_session_service,
)

log = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health(manager: IChromeInstanceManager = Depends(get_chrome_manager)):
    """No token required. Reports Chrome instance health + API status."""
    if manager is None:
        return {"ok": True, "instances": {}}
    instances = manager.list_instances()
    return {"ok": True, "instances": {i.name: i.model_dump() for i in instances}}


@router.get("/storage_state", dependencies=[Depends(require_token)])
async def storage_state(svc: SessionService = Depends(get_session_service)):
    try:
        state = svc.get_storage_state()
        return JSONResponse(content=state.model_dump())
    except Exception as e:
        log.warning("storage_state error: %r", e)
        return JSONResponse(status_code=503, content={"error": str(e)})


@router.get("/fingerprint", dependencies=[Depends(require_token)])
async def fingerprint(svc: SessionService = Depends(get_session_service)):
    fp = svc.get_fingerprint()
    return JSONResponse(content=json.loads(fp.model_dump_json()))


@router.get("/profile_zip", dependencies=[Depends(require_token)])
async def profile_zip(svc: SessionService = Depends(get_session_service)):
    try:
        path = svc.get_profile_zip()
        return FileResponse(
            path=str(path),
            media_type="application/zip",
            filename=path.name,
        )
    except Exception as e:
        log.warning("profile_zip error: %r", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/lock", dependencies=[Depends(require_token)])
async def lock(
    client: str = Query(default="unknown"),
    svc: LockService = Depends(get_lock_service),
):
    result = await svc.acquire(client)
    return result.model_dump()


@router.get("/unlock", dependencies=[Depends(require_token)])
async def unlock(
    client: str = Query(default="unknown"),
    svc: LockService = Depends(get_lock_service),
):
    result = await svc.release(client)
    return result.model_dump()
