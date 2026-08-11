from __future__ import annotations

import os
import threading
import time
import zipfile
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.ports.profile_repository import IProfileRepository

log = get_logger(__name__)

SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", r"Service Worker\CacheStorage",
    "GrShaderCache", "blob_storage", "Session Storage",
}
SKIP_EXTS = {".log", ".pma", ".tmp"}


class ProfileZipper(IProfileRepository):
    """IProfileRepository impl that compresses the master profile into
    profile.zip, excluding cache/junk and skipping locked files."""

    def __init__(self) -> None:
        self._mtime = 0.0
        self._lock = threading.Lock()

    def build_zip(self) -> Path:
        with self._lock:
            master = settings.master_dir
            tmp = settings.profile_zip.with_suffix(".tmp")
            log.info("comprimiendo perfil master...")
            count = 0
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                for root, dirs, files in os.walk(master):
                    rel = Path(root).relative_to(master)
                    skip = [d for d in dirs if d in SKIP_DIRS]
                    for s in skip:
                        dirs.remove(s)
                    for fname in files:
                        if any(fname.endswith(e) for e in SKIP_EXTS):
                            continue
                        fp = Path(root) / fname
                        arc = rel / fname
                        try:
                            info = zipfile.ZipInfo(str(arc))
                            try:
                                st = os.stat(fp)
                                t = time.localtime(st.st_mtime)
                                info.date_time = (
                                    max(t.tm_year, 1980), t.tm_mon, t.tm_mday,
                                    t.tm_hour, t.tm_min, t.tm_sec,
                                )
                                info.compress_type = zipfile.ZIP_DEFLATED
                                with open(fp, "rb") as fh:
                                    zf.writestr(info, fh.read())
                            except (ValueError, OSError):
                                info.date_time = (1980, 1, 1, 0, 0, 0)
                                info.compress_type = zipfile.ZIP_DEFLATED
                                with open(fp, "rb") as fh:
                                    zf.writestr(info, fh.read())
                            count += 1
                        except (PermissionError, OSError):
                            pass
            if settings.profile_zip.exists():
                settings.profile_zip.unlink()
            tmp.rename(settings.profile_zip)
            self._mtime = time.time()
            size_mb = settings.profile_zip.stat().st_size / 1024 / 1024
            log.info("profile.zip listo: %d archivos, %.1f MB", count, size_mb)
            return settings.profile_zip

    def get_zip_path(self) -> Path:
        if (
            not settings.profile_zip.exists()
            or (time.time() - self._mtime) > settings.PROFILE_ZIP_STALE_SEC
        ):
            self.build_zip()
        return settings.profile_zip
