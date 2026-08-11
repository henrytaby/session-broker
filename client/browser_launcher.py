from __future__ import annotations

import os
import time
from pathlib import Path

from app.core.logging import get_logger
from app.domain.models import Fingerprint
from app.infrastructure.fingerprint.fingerprint import (
    build_chromium_args,
    build_context_opts,
    init_script,
)

log = get_logger(__name__)

IGNORE_DEFAULT_ARGS = [
    "--enable-automation",
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=Automation",
]


def build_cookie_objects(ss_data: dict) -> list[dict]:
    """Build Playwright-compatible cookie dicts from the server's storage_state.

    sameSite falls back to "None"; expires/httpOnly/secure are only set when
    truthy. Ported verbatim from v9 client.
    """
    cookie_objects: list[dict] = []
    for c in ss_data.get("cookies", []):
        co = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
        }
        if c.get("expires") and c["expires"] > 0:
            co["expires"] = c["expires"]
        if c.get("httpOnly"):
            co["httpOnly"] = True
        if c.get("secure"):
            co["secure"] = True
        same = c.get("sameSite", "None")
        co["sameSite"] = same if same in ("Lax", "Strict", "None") else "None"
        cookie_objects.append(co)
    return cookie_objects


class BrowserLauncher:
    """Launches the local Chrome (patchright sync) with the full profile +
    injected cookies + fingerprint, and a debounced downloads handler."""

    def __init__(self, downloads_dir: Path) -> None:
        self._downloads = downloads_dir
        self._last_opened = 0.0

    def _on_download(self, download) -> None:
        try:
            nombre = download.suggested_filename
            ruta_final = self._downloads / nombre
            print(f"\n  Descargando: {nombre} ...")
            download.save_as(str(ruta_final))
            print(f"  Listo: {ruta_final}")
            now = time.time()
            if now - self._last_opened > 10:
                os.startfile(str(self._downloads))
                self._last_opened = now
        except Exception as e:
            print(f"  Error al guardar descarga: {e}")

    def run(
        self,
        fp: Fingerprint,
        ss_data: dict,
        profile_dir: Path,
        start_url: str,
    ) -> None:
        from patchright.sync_api import sync_playwright

        css = build_chromium_args(fp)
        ctx_opts = build_context_opts(fp)
        for k in ("viewport", "screen"):
            ctx_opts.pop(k, None)

        has_full_profile = (profile_dir / "Default").exists()

        with sync_playwright() as p:
            if has_full_profile:
                self._run_full_profile(p, fp, ss_data, profile_dir, css, ctx_opts, start_url)
            else:
                self._run_cookies_only(p, fp, ss_data, css, ctx_opts, start_url)

    def _launch_persistent(self, p, profile_dir, css, ctx_opts):
        try:
            return p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                channel="chrome",
                args=css,
                ignore_default_args=IGNORE_DEFAULT_ARGS,
                accept_downloads=True,
                no_viewport=True,
                **ctx_opts,
            )
        except Exception:
            return p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=css,
                ignore_default_args=IGNORE_DEFAULT_ARGS,
                accept_downloads=True,
                no_viewport=True,
                **ctx_opts,
            )

    def _run_full_profile(self, p, fp, ss_data, profile_dir, css, ctx_opts, start_url) -> None:
        print("  Modo: perfil completo (launch_persistent_context)")
        print(f"  Directorio perfil: {profile_dir}")

        context = self._launch_persistent(p, profile_dir, css, ctx_opts)
        context.add_init_script(init_script(fp))

        cookie_objects = build_cookie_objects(ss_data)
        print(f"  Inyectando {len(cookie_objects)} cookies desencriptadas...")
        context.add_cookies(cookie_objects)

        page = context.pages[0] if context.pages else context.new_page()
        print(f"  Navegando a: {start_url}")
        page.goto(start_url, wait_until="domcontentloaded", timeout=30000)

        context.on("page", lambda pg: pg.on("download", self._on_download))
        page.on("download", self._on_download)

        self._report(page.url)
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass

    def _run_cookies_only(self, p, fp, ss_data, css, ctx_opts, start_url) -> None:
        print("  Modo: solo cookies (sin perfil completo)")
        try:
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",
                args=css,
                ignore_default_args=IGNORE_DEFAULT_ARGS,
            )
        except Exception:
            browser = p.chromium.launch(
                headless=False,
                args=css,
                ignore_default_args=IGNORE_DEFAULT_ARGS,
            )

        context = browser.new_context(storage_state=ss_data, accept_downloads=True, **ctx_opts)
        context.add_init_script(init_script(fp))

        context.on("page", lambda pg: pg.on("download", self._on_download))
        page = context.new_page()
        page.on("download", self._on_download)

        print(f"  Navegando a: {start_url}")
        page.goto(start_url, wait_until="domcontentloaded", timeout=30000)

        self._report(page.url, cookies_only=True)
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    def _report(self, final_url: str, cookies_only: bool = False) -> None:
        needs_login = (
            "accounts.google.com" in final_url
            or "signin" in final_url.lower()
            or "ServiceLogin" in final_url
        )
        print("\n" + "=" * 55)
        if needs_login:
            print("  [!] Google pidio login. Posibles causas:")
            print("      - Servidor: abre Chrome con la cuenta y verifica sesion activa")
            print("      - Cookies expiradas: reinicia servidor con --refresh")
        else:
            print(f"  Sesion activa - URL: {final_url}")
        mode = "solo cookies" if cookies_only else "perfil completo (IndexedDB + SW + cookies)"
        print(f"  Perfil: {mode}")
        print(f"  Descargas -> {self._downloads}")
        print("  Cierra la ventana para salir.")
        print("=" * 55)
