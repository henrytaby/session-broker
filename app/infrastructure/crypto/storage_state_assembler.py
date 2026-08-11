from __future__ import annotations

import json
from pathlib import Path

from app.core.logging import get_logger
from app.domain.models import StorageState
from app.domain.ports.cookie_repository import ICookieRepository
from app.infrastructure.crypto.chrome_cookies import read_cookies_sqlite
from app.infrastructure.crypto.dpapi import get_master_key

log = get_logger(__name__)


class ChromeCookieRepository(ICookieRepository):
    """ICookieRepository impl backed by DPAPI + AES-GCM decryption of the
    master Chrome profile."""

    def get_storage_state(self, profile_dir: Path) -> StorageState:
        local_state = profile_dir / "Local State"
        cookies_db = profile_dir / "Default" / "Network" / "Cookies"
        if not local_state.exists():
            raise FileNotFoundError(f"No existe Local State en: {local_state}")
        if not cookies_db.exists():
            alt = profile_dir / "Default" / "Cookies"
            if alt.exists():
                cookies_db = alt
            else:
                raise FileNotFoundError(f"No existe Cookies DB en: {cookies_db}")

        master_key = get_master_key(local_state)
        log.debug("master key decrypted: %d bytes", len(master_key))
        cookies = read_cookies_sqlite(cookies_db, master_key)
        log.debug("cookies decrypted: %d", len(cookies))
        return StorageState(cookies=cookies, origins=[])

    def persist(self, state: StorageState, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(state.model_dump(), f, ensure_ascii=False, indent=2)
