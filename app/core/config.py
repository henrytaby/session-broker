from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SESSIONS_DIR: Path = Path(r"C:\chrome-sessions")
    MASTER_PROFILE_NAME: str = "master"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    AUTH_TOKEN: str = "gemini2024"
    CHROME_INSTANCES: int = 1
    CHROME_HEADLESS: bool = True
    GEMINI_CDP_PORT: int = 19230
    GEMINI_START_URL: str = "https://gemini.google.com/app"
    DEFAULT_START_URL: str = "https://gemini.google.com/"
    STORAGE_STATE_REFRESH_SEC: int = 180
    PROFILE_ZIP_STALE_SEC: int = 600
    SESSION_LOCK_TIMEOUT_SEC: int = 600
    PROFILE_ZIP_CACHE_HOURS: int = 1
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def master_dir(self) -> Path:
        return self.SESSIONS_DIR / self.MASTER_PROFILE_NAME

    @property
    def state_file(self) -> Path:
        return self.SESSIONS_DIR / "storage_state_live.json"

    @property
    def fingerprint_file(self) -> Path:
        return self.SESSIONS_DIR / "fingerprint.json"

    @property
    def profile_zip(self) -> Path:
        return self.SESSIONS_DIR / "profile.zip"

    def build_instances(self) -> dict[str, dict[str, int]]:
        """Map instance name -> chrome debug port (CDP local 127.0.0.1).

        The legacy v9 proxy `public_port` is removed: only `chrome_port` matters
        for local CDP access. Formula preserved: chrome_port = 19220 + i*10.
        """
        inst: dict[str, dict[str, int]] = {}
        for i in range(1, self.CHROME_INSTANCES + 1):
            name = f"pc{i}"
            inst[name] = {"chrome_port": 19220 + i * 10}
        return inst


settings = Settings()
