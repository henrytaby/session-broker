from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)


class ServerHttpClient:
    """httpx wrapper with retries for talking to the session server.

    Adds ?token=XXX to every request (v9-compatible) and tolerates transient
    network errors with a small retry loop.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 120.0, retries: int = 3) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._retries = retries

    def _url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{self._base}{path}{sep}token={self._token}"

    def get_json(self, path: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(self._url(path))
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:
                last_exc = e
                log.debug("get_json retry %d/%d: %r", attempt + 1, self._retries, e)
                time.sleep(2 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def download_file(self, path: str, dest: Path) -> None:
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    with client.stream("GET", self._url(path)) as resp:
                        resp.raise_for_status()
                        total = int(resp.headers.get("Content-Length", 0))
                        downloaded = 0
                        with open(dest, "wb") as f:
                            for chunk in resp.iter_bytes(chunk_size=65536):
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    pct = downloaded * 100 // total
                                    mb = downloaded / 1024 / 1024
                                    tmb = total / 1024 / 1024
                                    print(
                                        f"\r  Descargando: {mb:.1f}/{tmb:.1f} MB ({pct}%)",
                                        end="",
                                        flush=True,
                                    )
                print()
                return
            except Exception as e:
                last_exc = e
                log.debug("download retry %d/%d: %r", attempt + 1, self._retries, e)
                time.sleep(2 * (attempt + 1))
        raise last_exc  # type: ignore[misc]


def write_storage_state(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
