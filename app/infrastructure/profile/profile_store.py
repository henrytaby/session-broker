from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def is_profile_locked(profile_dir: Path) -> bool:
    """A profile is "locked" when its Cookies/Web Data SQLite files cannot be
    opened exclusively (another Chrome holds them)."""
    for f in [
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Web Data",
    ]:
        if not f.exists():
            continue
        try:
            with open(f, "rb"):
                pass
        except PermissionError:
            return True
    return False


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


def force_close_chrome() -> None:
    import os

    os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
    time.sleep(3)


def copy_profile_from_master(instance_name: str) -> Path:
    """Copy the master profile to an instance dir via robocopy (fast, multi-threaded)."""
    src = settings.master_dir
    dst = settings.SESSIONS_DIR / instance_name
    import os

    if is_profile_locked(src):
        log.warning("perfil master bloqueado, forzando cierre...")
        force_close_chrome()
        if is_profile_locked(src):
            raise PermissionError("Perfil master bloqueado")
    log.info("copiando master -> %s ...", instance_name)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
        time.sleep(0.5)
    os.system(
        f'robocopy "{src}" "{dst}" /E /ZB /R:1 /W:1 /MT:8 /NFL /NDL /NJH'
    )
    remove_lock_files(dst)
    log.info("%s listo", instance_name)
    return dst
