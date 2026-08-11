from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import StorageState
from app.domain.ports.cookie_repository import ICookieRepository
from app.domain.ports.fingerprint_provider import IFingerprintProvider
from app.domain.ports.profile_repository import IProfileRepository

log = get_logger(__name__)


class SessionService:
    """Orchestrates the session-sharing data: storage_state (decrypted cookies),
    profile.zip and the fingerprint. Delegates the heavy work to injected ports."""

    def __init__(
        self,
        cookie_repo: ICookieRepository,
        profile_repo: IProfileRepository,
        fingerprint_provider: IFingerprintProvider,
    ) -> None:
        self._cookies = cookie_repo
        self._profiles = profile_repo
        self._fp = fingerprint_provider

    def refresh_storage_state(self) -> StorageState:
        state = self._cookies.get_storage_state(settings.master_dir)
        self._cookies.persist(state, settings.state_file)
        log.info("storage_state refrescado: %d cookies", len(state.cookies))
        return state

    def get_storage_state(self) -> StorageState:
        if not settings.state_file.exists():
            return self.refresh_storage_state()
        try:
            data = json.loads(settings.state_file.read_text(encoding="utf-8"))
            return StorageState.model_validate(data)
        except Exception as e:
            log.warning("storage_state corrupto, regenerando: %r", e)
            return self.refresh_storage_state()

    def get_profile_zip(self) -> Path:
        return self._profiles.get_zip_path()

    def get_fingerprint(self):
        return self._fp.current()
