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

# Directories skipped by SIMPLE NAME (os.walk yields plain dir names in
# `dirs`, NOT nested rel-paths — so each entry here must be a single segment,
# e.g. "CacheStorage" not "Service Worker\CacheStorage", otherwise the match
# silently never fires and the dir ships in the zip).
SKIP_DIRS = {
    # JIT + HTTP caches (regenerables; no valor de sesion)
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "GPUPersistentCache", "DawnWebGPUCache", "DawnGraphiteCache",
    # Service Worker: ScriptCache mantiene los SW; CacheStorage es el bloat
    # mas grande del perfil (~500MB de respuestas cacheadas, regenerables).
    "CacheStorage",
    # Caches de componentes / modelos de Chrome (se redescargan solos)
    "optimization_guide_model_store", "OptimizationGuideModelsManifest",
    "component_crx_cache", "extensions_crx_cache",
    "OnDeviceHeadSuggestModel", "Subresource Filter", "OptimizationHints",
    "Safe Browsing", "SafetyTips", "PKIMetadata", "TrustTokenKeyCommitments",
    "CertificateRevocation", "FileTypePolicies", "AmountExtractionHeuristicRegexes",
    "CaptchaProviders", "SSLErrorAssistant", "OriginTrials",
    "WidevineCdm", "WasmTtsEngine", "MEIPreload", "hyphen-data",
    "FirstPartySetsPreloaded", "PrivacySandboxAttestationsPreloaded",
    "Crowd Deny", "RecoveryImproved", "segmentation_platform",
    "ZxcvbnData", "ActorSafetyLists", "Variations",
    # Telemetria/Crashes (no aportan nada a la sesion)
    "Crashpad", "BrowserMetrics",
    # Sesion viva de pestañas: se regenera al abrir Chrome del cliente
    "Sessions",
    # PWA / FileSystem sandboxed: 19MB que no aportan al login de Google
    "File System",
    # IndexedDB sandboxed de extensiones sueltas (no el de Google)
    "Session Storage",
}
# Specific files (by suffix) we never ship: logs, pma (metrics), temp.
SKIP_EXTS = {".log", ".pma", ".tmp", ".bak", ".old"}
# Specific file basenames we skip regardless of extension (pma-by-name is
# already covered by SKIP_EXTS, but keep explicit ones for clarity).
SKIP_FILES = {
    "BrowserMetrics-spare.pma",
    "CrashpadMetrics-active.pma",
    "4159125f-a04f-4b4b-b9a2-2691d2827f57.tmp",
}


class ProfileZipper(IProfileRepository):
    """IProfileRepository impl that compresses the master profile into
    profile.zip, excluding cache/junk and skipping locked files.

    The SKIP_DIRS set is matched by single-segment dir NAME (what os.walk
    puts in `dirs`), not by nested rel-path. Writing "Service Worker\\Cache"
    here would never match and silently ship ~hundreds of MB of cache.
    """

    def __init__(self) -> None:
        self._mtime = 0.0
        self._lock = threading.Lock()

    def build_zip(self) -> Path:
        with self._lock:
            master = settings.master_dir
            tmp = settings.profile_zip.with_suffix(".tmp")
            log.info("comprimiendo perfil master...")
            count = 0
            skipped = 0
            # compresslevel=6: decent ratio without being CPU-bound on a
            # 1-time-per-10min build. Was =1 (~30% bigger, marginal CPU win).
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for root, dirs, files in os.walk(master):
                    rel = Path(root).relative_to(master)
                    # Prune in-place so os.walk does not descend into them.
                    skip = [d for d in dirs if d in SKIP_DIRS]
                    for s in skip:
                        dirs.remove(s)
                        skipped += 1
                    for fname in files:
                        if any(fname.endswith(e) for e in SKIP_EXTS):
                            continue
                        if fname in SKIP_FILES:
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
            log.info("profile.zip listo: %d archivos (%d dirs saltados), %.1f MB",
                     count, skipped, size_mb)
            return settings.profile_zip

    def get_zip_path(self) -> Path:
        if (
            not settings.profile_zip.exists()
            or (time.time() - self._mtime) > settings.PROFILE_ZIP_STALE_SEC
        ):
            self.build_zip()
        return settings.profile_zip
