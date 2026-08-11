from __future__ import annotations

from pathlib import Path


def find_chrome_official() -> str:
    """Locate the official Chrome executable (not Chromium from Playwright)."""
    for p in [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]:
        if p.exists():
            return str(p)
    raise FileNotFoundError("Chrome oficial no encontrado")
