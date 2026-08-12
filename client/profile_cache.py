from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from client.http_client import ServerHttpClient

log = get_logger(__name__)

# Files inside the downloaded profile.zip that are encrypted with the SERVER's
# Windows DPAPI master key (stored in `Local State`). On any OTHER PC the DPAPI
# key is bound to a different Windows user SID, so Chrome on the client cannot
# decrypt these files. If we leave them in place, Chrome loads the SQLite DB
# on `launch_persistent_context`, fails to decrypt every cookie row, and ends up
# in a "no session" state — even though we later call `context.add_cookies()`
# with the plaintext cookies from /storage_state. The plaintext injection races
# against Chrome's own state load (Service Workers + IndexedDB OAuth tokens are
# validated against the SQLite cookies, which are empty/garbage on the client).
#
# Fix: strip these files after extraction so Chrome recreates them fresh with
# the LOCAL machine's DPAPI key, and the plaintext cookies we inject via
# `add_cookies()` become the single source of truth. IndexedDB, Service Worker
# ScriptCache and Local Storage (LevelDB, NOT DPAPI-encrypted) are preserved
# and carry the actual OAuth session tokens.
DPAPI_BOUND_FILES: tuple[str, ...] = (
    "Local State",                          # contains the encrypted master key
    "Default/Network/Cookies",               # cookie SQLite (encrypted values)
    "Default/Login Data",                    # saved credentials (encrypted)
    "Default/Web Data",                     # autofill / payment (encrypted)
    "Default/Account Web Data",              # account-specific (encrypted)
)


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


def strip_dpapi_encrypted_files(profile_dir: Path) -> int:
    """Remove SQLite/JSON files bound to the SERVER's Windows DPAPI master key.

    These files come from the server's profile.zip but are encrypted with a
    DPAPI key tied to the server's Windows user. On the client machine Chrome
    cannot decrypt them, so leaving them in place corrupts the session state
    (cookies / saved logins appear empty). Chrome recreates fresh empty copies
    on first launch with the LOCAL machine's DPAPI key; the plaintext cookies
    we inject via `context.add_cookies()` then become authoritative.

    Returns the number of files actually removed.
    """
    removed = 0
    for rel in DPAPI_BOUND_FILES:
        target = profile_dir / rel
        try:
            if target.exists():
                target.unlink()
                removed += 1
        except OSError as e:
            log.debug("no se pudo borrar %s: %r", rel, e)
    return removed


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
            stripped = strip_dpapi_encrypted_files(self._dir)
            if stripped:
                log.info("stripped %d DPAPI-bound file(s) del cache local", stripped)
            log.info("perfil cacheado (< 1h), reutilizando: %s", self._dir)
            return True

        self._dir.mkdir(parents=True, exist_ok=True)
        # Download to a sibling temp file OUTSIDE self._dir: self._dir is wiped
        # before extraction, so a zip stored inside it would be deleted too.
        zip_path = self._dir.parent / "profile_download.zip"
        try:
            http.download_file("/profile_zip", zip_path)
        except Exception as e:
            log.warning("error descargando perfil: %r — modo solo-cookies", e)
            try:
                zip_path.unlink()
            except Exception:
                pass
            return False

        if zip_path.exists() and zip_path.stat().st_size > 0:
            log.info("extrayendo perfil...")
            if self._dir.exists():
                shutil.rmtree(self._dir, ignore_errors=True)
                self._dir.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(self._dir)
            except (zipfile.BadZipFile, OSError) as e:
                log.warning("zip corrupto o lectura fallida: %r — modo solo-cookies", e)
                try:
                    zip_path.unlink()
                except Exception:
                    pass
                return False
            remove_lock_files(self._dir)
            stripped = strip_dpapi_encrypted_files(self._dir)
            if stripped:
                log.info("stripped %d DPAPI-bound file(s) tras extraccion", stripped)
            try:
                zip_path.unlink()
            except Exception:
                pass
            log.info("perfil extraido en: %s", self._dir)
            return True
        return False
