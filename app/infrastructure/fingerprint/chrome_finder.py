from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


def detect_chrome_version(chrome_exe: str | None = None) -> int:
    """Detect the real installed Chrome major version so the UA matches."""
    if chrome_exe is None:
        for p in [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]:
            if p.exists():
                chrome_exe = str(p)
                break
    if not chrome_exe or not Path(chrome_exe).exists():
        return 127
    try:
        out = subprocess.check_output(
            f'powershell -command "(Get-Item \'{chrome_exe}\').VersionInfo.ProductVersion"',
            shell=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="ignore").strip()
        m = re.search(r"(\d+)\.", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 127


def detect_webgl_renderer() -> str:
    """Detect the real WebGL renderer of the server GPU (via dxdiag)."""
    try:
        out = subprocess.check_output(
            'powershell -command "dxdiag /t C:\\\\Users\\\\Public\\\\dxdiag.txt; '
            'Start-Sleep -Seconds 2; Get-Content C:\\\\Users\\\\Public\\\\dxdiag.txt"',
            shell=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).decode("utf-8", errors="ignore")
        for m in re.finditer(r"Card name:\s*(.+)", out):
            gpu = m.group(1).strip()
            return f"ANGLE (NVIDIA, {gpu} Direct3D11 vs_5_0 ps_5_0, D3D11)"
    except Exception:
        pass
    return "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
