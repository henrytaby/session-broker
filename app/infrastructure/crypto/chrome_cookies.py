from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from app.core.logging import get_logger
from app.domain.models import Cookie
from app.infrastructure.crypto.aes_gcm import decrypt_value

log = get_logger(__name__)

# Windows FILETIME (100ns ticks since 1601) -> Unix epoch seconds.
_FILETIME_EPOCH = 11644473600000000

_SAMESITE_MAP = {0: "None", 1: "Lax", 2: "Strict", -1: "None"}


def read_cookies_sqlite(cookies_path: Path, master_key: bytes) -> list[Cookie]:
    """Read the Chrome cookies SQLite DB (copied to a tmp file first) and
    decrypt every row into a Playwright-compatible Cookie list."""
    tmp_db = Path(tempfile.gettempdir()) / "chrome_cookies_tmp.db"
    shutil.copy2(cookies_path, tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        try:
            cursor.execute(
                "SELECT host_key, name, path, encrypted_value, expires_utc, "
                "is_secure, is_httponly, samesite, source_port FROM cookies"
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            cursor.execute(
                "SELECT host_key, name, path, encrypted_value, expires_utc, "
                "is_secure, is_httponly, samesite FROM cookies"
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
        try:
            tmp_db.unlink()
        except Exception:
            pass

    cookies: list[Cookie] = []
    for r in rows:
        enc = r["encrypted_value"]
        if isinstance(enc, memoryview):
            enc = bytes(enc)
        value = decrypt_value(enc, master_key) or ""

        expires_utc = r["expires_utc"]
        if expires_utc and expires_utc > 0:
            expires_unix = (expires_utc - _FILETIME_EPOCH) // 1000000
            if expires_unix <= 0:
                expires_unix = -1
        else:
            expires_unix = -1

        samesite = (
            _SAMESITE_MAP.get(r["samesite"], "None")
            if "samesite" in r.keys()
            else "None"
        )

        cookies.append(
            Cookie(
                name=r["name"],
                value=value,
                domain=r["host_key"],
                path=r["path"],
                expires=expires_unix,
                httpOnly=bool(r["is_httponly"]),
                secure=bool(r["is_secure"]),
                sameSite=samesite,
            )
        )

    return cookies
