from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import Fingerprint
from app.domain.ports.fingerprint_provider import IFingerprintProvider
from app.infrastructure.fingerprint.chrome_finder import (
    detect_chrome_version,
    detect_webgl_renderer,
)
from app.infrastructure.fingerprint.fingerprint import default_fingerprint

log = get_logger(__name__)


class FileFingerprintProvider(IFingerprintProvider):
    """Builds the fingerprint from the real installed Chrome, persists it to
    the fingerprint.json file and serves the cached value."""

    def __init__(self, chrome_exe: str | None = None) -> None:
        self._chrome_exe = chrome_exe
        self._fp: Fingerprint | None = None

    def refresh(self) -> Fingerprint:
        cv = detect_chrome_version(self._chrome_exe)
        wr = detect_webgl_renderer()
        fp = default_fingerprint(chrome_version=cv)
        fp.webgl_renderer = wr
        self._fp = fp
        try:
            settings.fingerprint_file.parent.mkdir(parents=True, exist_ok=True)
            settings.fingerprint_file.write_text(
                fp.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("could not persist fingerprint file: %r", e)
        log.info("fingerprint refreshed (Chrome v%s, %s)", cv, wr)
        return fp

    def current(self) -> Fingerprint:
        if self._fp is not None:
            return self._fp
        fp_file = settings.fingerprint_file
        if fp_file.exists():
            try:
                self._fp = Fingerprint.model_validate_json(
                    fp_file.read_text(encoding="utf-8")
                )
                return self._fp
            except Exception:
                pass
        return self.refresh()
