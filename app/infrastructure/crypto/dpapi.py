from __future__ import annotations

import base64
import json
from pathlib import Path

import win32crypt

from app.core.logging import get_logger
from app.domain.exceptions import DecryptError

log = get_logger(__name__)

DPAPI_PREFIX = b"DPAPI"


def get_master_key(local_state_path: Path) -> bytes:
    """Read Local State, strip the "DPAPI" prefix and unprotect the master key."""
    try:
        with open(local_state_path, encoding="utf-8") as f:
            local_state = json.load(f)
        encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(encrypted_key_b64)
        if encrypted_key.startswith(DPAPI_PREFIX):
            encrypted_key = encrypted_key[len(DPAPI_PREFIX):]
        master_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
        return master_key[1]
    except Exception as e:
        raise DecryptError(f"Failed to read master key from {local_state_path}: {e}") from e
