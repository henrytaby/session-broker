from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Query, Request

from app.core.config import settings


def _extract_token(request: Request) -> str:
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token or ""


def require_token(token: str = Depends(_extract_token)) -> None:
    """FastAPI dependency: constant-time token comparison.

    `?token=XXX` query param (v9-compatible) or `Authorization: Bearer XXX`.
    Never logs the token value.
    """
    if not secrets.compare_digest(token, settings.AUTH_TOKEN):
        raise HTTPException(status_code=403, detail="token invalido")


def optional_token(token: str = Query(default="")) -> str:
    return token
