from __future__ import annotations

from app.domain.ports.chrome_manager import IChromeInstanceManager
from app.domain.ports.cookie_repository import ICookieRepository
from app.domain.ports.fingerprint_provider import IFingerprintProvider
from app.domain.ports.profile_repository import IProfileRepository
from app.domain.ports.session_lock import ISessionLock
from app.infrastructure.crypto.storage_state_assembler import ChromeCookieRepository
from app.infrastructure.fingerprint.provider import FileFingerprintProvider
from app.infrastructure.lock.in_memory_lock import InMemorySessionLock
from app.infrastructure.profile.chrome_finder import find_chrome_official
from app.infrastructure.profile.chrome_process import ChromeInstanceManager
from app.infrastructure.profile.profile_zipper import ProfileZipper


def build_default_adapters(
    *,
    chrome_manager: IChromeInstanceManager | None = None,
    cookie_repo: ICookieRepository | None = None,
    profile_repo: IProfileRepository | None = None,
    fingerprint_provider: IFingerprintProvider | None = None,
    session_lock: ISessionLock | None = None,
) -> dict:
    """Wire the concrete adapters (composition root).

    Any None argument is replaced with its default production implementation,
    so callers (tests) can inject fakes for just the seams they care about.
    """
    if cookie_repo is None:
        cookie_repo = ChromeCookieRepository()
    if profile_repo is None:
        profile_repo = ProfileZipper()
    if fingerprint_provider is None:
        fingerprint_provider = FileFingerprintProvider()
    if session_lock is None:
        session_lock = InMemorySessionLock()
    if chrome_manager is None:
        try:
            chrome_exe = find_chrome_official()
            chrome_manager = ChromeInstanceManager(chrome_exe=chrome_exe)
        except FileNotFoundError:
            chrome_manager = None
    return {
        "cookie_repo": cookie_repo,
        "profile_repo": profile_repo,
        "fingerprint_provider": fingerprint_provider,
        "session_lock": session_lock,
        "chrome_manager": chrome_manager,
    }
