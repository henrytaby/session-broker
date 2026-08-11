from __future__ import annotations

import json
import sqlite3
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings


@pytest.fixture
def tmp_master_profile(tmp_path: Path) -> Path:
    """Build a fake Chrome master profile with a Cookies SQLite DB and Local
    State, for crypto tests. The master_key is a fixed 32-byte value and we
    stub win32crypt.CryptUnprotectData to return it."""
    profile = tmp_path / "master"
    (profile / "Default" / "Network").mkdir(parents=True, exist_ok=True)

    master_key = b"0123456789ABCDEF0123456789ABCDEF"  # 32 bytes
    import base64 as _b64

    encrypted_key_b64 = _b64.b64encode(b"DPAPI" + master_key).decode()
    local_state = {"os_crypt": {"encrypted_key": encrypted_key_b64}}
    (profile / "Local State").write_text(json.dumps(local_state), encoding="utf-8")

    cookies_db = profile / "Default" / "Network" / "Cookies"
    conn = sqlite3.connect(str(cookies_db))
    conn.execute(
        "CREATE TABLE cookies ("
        "host_key TEXT, name TEXT, path TEXT, encrypted_value BLOB, "
        "expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER, "
        "samesite INTEGER, source_port INTEGER)"
    )
    conn.execute(
        "CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR)"
    )

    # Build a v10 AES-GCM encrypted cookie using the master key.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aesgcm = AESGCM(master_key)
    nonce = b"012345678901"
    plaintext = b"my-cookie-value"
    ct = aesgcm.encrypt(nonce, plaintext, None)
    v10_value = b"v10" + nonce + ct
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)",
        (".google.com", "SID", "/", v10_value, 0, 1, 1, 1, 0),
    )

    # A v10 cookie WITH the 32-byte domain hash prefix (Chrome v127+).
    domain_hash = b"x" * 32
    ct2 = aesgcm.encrypt(nonce, domain_hash + b"hashed-cookie", None)
    v10_hashed = b"v10" + nonce + ct2
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)",
        (".google.com", "HASHED", "/", v10_hashed, 0, 1, 0, 2, 0),
    )

    # A plain (non v10) DPAPI-protected value.
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)",
        (".example.com", "PLAIN", "/", b"plain-bytes", 0, 0, 0, 0, 0),
    )

    # A cookie with a real future expiry (FILETIME) -> exercises expires_utc conv.
    expires_unix = 2000000000
    expires_filetime = expires_unix * 1000000 + 11644473600000000
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)",
        (".google.com", "EXP", "/", v10_value, expires_filetime, 1, 1, 1, 0),
    )

    conn.commit()
    conn.close()

    # Patch win32crypt to return our fixed master key (avoids needing real DPAPI).
    fake = master_key

    def fake_unprotect(data, *a, **kw):
        return (None, fake)

    with patch("app.infrastructure.crypto.dpapi.win32crypt") as mock_win32, \
         patch("app.infrastructure.crypto.aes_gcm.win32crypt") as mock_win32b:
        mock_win32.CryptUnprotectData = fake_unprotect
        mock_win32b.CryptUnprotectData = fake_unprotect
        yield profile


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch):
    """Redirect SESSIONS_DIR to a tmp path so tests never touch real data."""
    monkeypatch.setattr(settings, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(settings, "MASTER_PROFILE_NAME", "master")
    yield
