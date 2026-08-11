from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from client.http_client import ServerHttpClient

log = get_logger(__name__)


def remove_lock_files(profile_dir: Path) -> None:
    for f in [
        profile_dir / "SingletonLock",
        profile_dir / "SingletonCookie",
        profile_dir / "SingletonSocket",
        profile_dir / "Default" / "LOCK",
        profile_dir / "Default" / "LOCKING",
    ]:
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass


class ProfileCache:
    """Downloads + extracts the server's profile.zip with a local cache (1h by
    default). --force bypasses the cache."""

    def __init__(self, local_dir: Path) -> None:
        self._dir = local_dir

    @property
    def dir(self) -> Path:
        return self._dir

    def is_fresh(self) -> bool:
        default = self._dir / "Default"
        if not default.exists():
            return False
        try:
            age = time.time() - default.stat().st_mtime
            max_age = settings.PROFILE_ZIP_CACHE_HOURS * 3600
            return age < max_age
        except Exception:
            return False

    def has_full_profile(self) -> bool:
        return (self._dir / "Default").exists()

    def download_and_extract(self, http: ServerHttpClient, force: bool) -> bool:
        """Returns True if a full profile is available locally after this call."""
        if self.has_full_profile() and not force and self.is_fresh():
            remove_lock_files(self._dir)
            log.info("perfil cacheado (< 1h), reutilizando: %s", self._dir)
            return True

        log.info("descargando perfil completo del servidor...")
        zip_path = self._dir / "profile_download.zip"
        try:
            http.download_file("/profile_zip", zip_path)
        except Exception as e:
            log.warning("error descargando perfil: %r — modo solo-cookies", e)
            return False

        if zip_path.exists():
            log.info("extrayendo perfil...")
            if self._dir.exists():
                shutil.rmtree(self._dir, ignore_errors=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(self._dir)
            remove_lock_files(self._dir)
            try:
                zip_path.unlink()
            except Exception:
                pass
            log.info("perfil extraido en: %s", self._dir)
            return True
        self._dir.mkdir(parents=True, exist_ok=True)
        return False
