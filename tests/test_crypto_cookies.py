from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.crypto.chrome_cookies import read_cookies_sqlite
from app.infrastructure.crypto.storage_state_assembler import ChromeCookieRepository

MASTER_KEY = b"0123456789ABCDEF0123456789ABCDEF"


def _build_cookies_db(db_path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE cookies ("
        "host_key TEXT, name TEXT, path TEXT, encrypted_value BLOB, "
        "expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER, "
        "samesite INTEGER, source_port INTEGER)"
    )
    conn.execute(
        "CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR)"
    )
    for r in rows:
        conn.execute("INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)", r)
    conn.commit()
    conn.close()


def test_read_cookies_samesite_and_expires(tmp_path: Path):
    db = tmp_path / "Cookies"
    _build_cookies_db(
        db,
        [
            # samesite=1 (Lax), expired (utc=0 -> -1)
            (".google.com", "A", "/", b"", 0, 1, 1, 1, 0),
            # samesite=2 (Strict), future expiry
            (".google.com", "B", "/", b"", 2000000000 * 1000000 + 11644473600000000, 0, 0, 2, 0),
            # samesite=-1 -> None
            (".google.com", "C", "/", b"", 0, 0, 0, -1, 0),
        ],
    )
    cookies = read_cookies_sqlite(db, MASTER_KEY)
    assert len(cookies) == 3
    by_name = {c.name: c for c in cookies}
    assert by_name["A"].sameSite == "Lax"
    assert by_name["A"].expires == -1
    assert by_name["B"].sameSite == "Strict"
    assert by_name["B"].expires == 2000000000
    assert by_name["C"].sameSite == "None"
    assert by_name["A"].secure is True
    assert by_name["A"].httpOnly is True


def test_read_cookies_falls_back_to_no_source_port(tmp_path: Path):
    """When source_port column is missing, the 8-column SELECT is used."""
    db = tmp_path / "Cookies"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE cookies ("
        "host_key TEXT, name TEXT, path TEXT, encrypted_value BLOB, "
        "expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER, "
        "samesite INTEGER)"
    )
    conn.execute("INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?)",
                 (".google.com", "X", "/", b"", 0, 0, 0, 0))
    conn.commit()
    conn.close()
    cookies = read_cookies_sqlite(db, MASTER_KEY)
    assert len(cookies) == 1
    assert cookies[0].name == "X"
    assert cookies[0].sameSite == "None"


def test_repository_get_storage_state(tmp_master_profile: Path):
    repo = ChromeCookieRepository()
    state = repo.get_storage_state(tmp_master_profile)
    names = {c.name: c for c in state.cookies}
    assert "SID" in names
    assert names["SID"].value == "my-cookie-value"
    # domain-hash prefixed value is decoded without the 32 bytes
    assert names["HASHED"].value == "hashed-cookie"
    assert state.origins == []


def test_repository_persist_roundtrip(tmp_master_profile: Path, tmp_path: Path):
    repo = ChromeCookieRepository()
    state = repo.get_storage_state(tmp_master_profile)
    out = tmp_path / "out.json"
    repo.persist(state, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "cookies" in data
    assert len(data["cookies"]) == len(state.cookies)
