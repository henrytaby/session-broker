from __future__ import annotations

import os
import subprocess
import time
import urllib.request

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import InstanceInfo
from app.domain.ports.chrome_manager import IChromeInstanceManager
from app.infrastructure.profile.chrome_finder import find_chrome_official
from app.infrastructure.profile.profile_store import (
    copy_profile_from_master,
)

log = get_logger(__name__)

CHROME_HOST = "127.0.0.1"


def kill_by_port(port: int) -> None:
    cmd = (
        f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{port}\') '
        f"do taskkill /PID %a /F /T >nul 2>&1"
    )
    os.system(cmd)


def is_chrome_alive(chrome_port: int, timeout: int = 3) -> bool:
    try:
        url = f"http://{CHROME_HOST}:{chrome_port}/json/version"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def open_keepalive_page(chrome_port: int) -> bool:
    try:
        url = f"http://{CHROME_HOST}:{chrome_port}/json/new?url=about:blank"
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


class ChromeInstanceManager(IChromeInstanceManager):
    """IChromeInstanceManager impl launching headless Chrome as subprocesses
    (one per instance) and watching them via the CDP /json/version endpoint."""

    def __init__(self, chrome_exe: str | None = None, headless: bool | None = None) -> None:
        self._chrome_exe = chrome_exe or find_chrome_official()
        self._headless = settings.CHROME_HEADLESS if headless is None else headless
        self._instances = settings.build_instances()
        self._processes: dict[str, subprocess.Popen] = {}

    @property
    def instances(self) -> dict[str, dict[str, int]]:
        return self._instances

    def _launch_args(self, instance_name: str, chrome_port: int) -> list[str]:
        user_data = settings.SESSIONS_DIR / instance_name
        return [
            self._chrome_exe,
            f"--user-data-dir={user_data}",
            "--profile-directory=Default",
            f"--remote-debugging-port={chrome_port}",
            "--headless=new" if self._headless else "--headless=false",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process,ChromeCleanup",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--lang=es-419",
        ]

    def launch(self, name: str) -> None:
        cfg = self._instances[name]
        chrome_port = cfg["chrome_port"]
        log_file = settings.SESSIONS_DIR / f"{name}.log"
        f = open(log_file, "w")
        args = self._launch_args(name, chrome_port)
        proc = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT)
        self._processes[name] = proc
        log.info("instancia %s lanzada (puerto %d)", name, chrome_port)

    def launch_all(self) -> None:
        for name in self._instances:
            self.launch(name)
            time.sleep(3)
            cfg = self._instances[name]
            if is_chrome_alive(cfg["chrome_port"]):
                open_keepalive_page(cfg["chrome_port"])
                log.info("%s OK puerto %d", name, cfg["chrome_port"])
            else:
                log.warning("%s no respondio", name)
            time.sleep(1)

    def is_alive(self, chrome_port: int) -> bool:
        return is_chrome_alive(chrome_port)

    def open_keepalive_page(self, chrome_port: int) -> bool:
        return open_keepalive_page(chrome_port)

    def restart(self, name: str) -> bool:
        cfg = self._instances[name]
        chrome_port = cfg["chrome_port"]
        log.info("%s cayo. Reiniciando...", name)
        kill_by_port(chrome_port)
        time.sleep(2)
        self.launch(name)
        time.sleep(3)
        if is_chrome_alive(chrome_port):
            open_keepalive_page(chrome_port)
            log.info("%s reiniciado OK", name)
            return True
        return False

    def list_instances(self) -> list[InstanceInfo]:
        return [
            InstanceInfo(
                name=name,
                chrome_port=cfg["chrome_port"],
                alive=is_chrome_alive(cfg["chrome_port"]),
            )
            for name, cfg in self._instances.items()
        ]

    def shutdown(self) -> None:
        for cfg in self._instances.values():
            kill_by_port(cfg["chrome_port"])
        for proc in self._processes.values():
            try:
                proc.terminate()
            except Exception:
                pass


def refresh_master_to_instances() -> None:
    """Copy master -> each instance dir (used by --refresh / first-time setup)."""
    instances = settings.build_instances()
    for name in instances:
        copy_profile_from_master(name)


def setup_firewall() -> None:
    """Open firewall only for the API port (CDP proxy ports removed)."""
    log.info("configurando firewall...")
    os.system('netsh advfirewall firewall delete rule name="Session-API" >nul 2>&1')
    os.system(
        f'netsh advfirewall firewall add rule name="Session-API" dir=in '
        f"action=allow protocol=TCP localport={settings.API_PORT} profile=any"
    )
