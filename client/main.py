from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.core.logging import setup_logging
from app.domain.models import Fingerprint
from app.infrastructure.fingerprint.chrome_finder import detect_chrome_version
from app.infrastructure.fingerprint.fingerprint import reconcile_chrome_version
from client.browser_launcher import BrowserLauncher
from client.http_client import ServerHttpClient, write_storage_state
from client.profile_cache import ProfileCache

SERVER_URL_DEFAULT = "http://192.168.68.61:8000"
START_URL_DEFAULT = "https://gemini.google.com/"
_CLIENT_DATA_DIR = Path(__file__).resolve().parent / "data"
LOCAL_PROFILE_DIR = _CLIENT_DATA_DIR / "chrome_profile_local"
LOCAL_STATE_FILE = _CLIENT_DATA_DIR / "storage_state_local.json"
DOWNLOADS_DIR = _CLIENT_DATA_DIR / "Descargas_Bot"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Session Sharing Client (v9 clean arch)")
    parser.add_argument("server_url", nargs="?", default=SERVER_URL_DEFAULT)
    parser.add_argument("start_url", nargs="?", default=None)
    parser.add_argument("--no-lock", action="store_true", help="Desactiva sistema de turnos")
    parser.add_argument("--force", action="store_true", help="Forzar descarga de perfil")
    return parser.parse_args(argv)


def _banner(text: str, char: str = "=", width: int = 55) -> None:
    print()
    print(char * width)
    print(text)
    print(char * width)


def _acquire_turn(http: ServerHttpClient, client_id: str) -> bool:
    print(f"\n[0/4] Solicitando turno (cliente: {client_id})...")
    try:
        lock_data = http.get_json(f"/lock?client={client_id}")
    except Exception:
        lock_data = {"locked": False}

    if not lock_data.get("locked"):
        holder = lock_data.get("holder", "?")
        remaining = lock_data.get("remaining_sec", 0)
        print(f"  OCUPADO por: {holder}")
        if remaining > 0:
            print(f"  Esperando liberacion... ({remaining}s restantes)")
        wait_start = time.time()
        while not lock_data.get("locked"):
            if time.time() - wait_start > 120:
                print("  Tiempo de espera agotado. Continuando de todas formas...")
                break
            time.sleep(5)
            try:
                lock_data = http.get_json(f"/lock?client={client_id}")
            except Exception:
                break
            remaining = lock_data.get("remaining_sec", 0)
            print(f"\r  Esperando... {remaining}s  ", end="", flush=True)
        print()
    print("  Turno concedido.")
    return True


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    server_url = args.server_url.rstrip("/")
    start_url = args.start_url or settings.DEFAULT_START_URL

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    client_id = os.environ.get("COMPUTERNAME", "pc-desconocido")

    http = ServerHttpClient(server_url, settings.AUTH_TOKEN)

    # ---- 0. Turnos
    if args.no_lock:
        print("\n[0/4] Sistema de turnos DESACTIVADO (--no-lock)")
    else:
        _acquire_turn(http, client_id)

    _banner("  SESSION CLIENT v9  -  Perfil hibrido + huella")

    # ---- 1. Fingerprint
    print("\n[1/4] Obteniendo huella del servidor...")
    try:
        fp_data = http.get_json("/fingerprint")
    except Exception as e:
        print(f"  ERROR: no se pudo conectar al servidor.\n  {e}")
        print("\nVerifica:\n  1. Servidor corriendo en la PC central\n  2. Firewall permite " + server_url)
        return
    fp = Fingerprint(**fp_data)
    # Reconcile UA + sec-ch-ua to the LOCAL Chrome version to avoid UA/TLS
    # (JA3) mismatch: the server's fingerprint may use a different Chrome major
    # version than the local binary actually making the requests.
    local_cv = detect_chrome_version()
    fp = reconcile_chrome_version(fp, local_cv)
    print(f"  OK  UA: {fp.user_agent[:55]}")
    print(f"  OK  TZ: {fp.timezone}  Screen: {fp.screen_width}x{fp.screen_height}")
    if local_cv:
        print(f"  OK  Chrome local detectado: v{local_cv}")

    # ---- 2. Perfil completo (con cache)
    print("\n[2/4] Descargando perfil completo del servidor...")
    cache = ProfileCache(LOCAL_PROFILE_DIR)
    cache.download_and_extract(http, args.force)

    # ---- 3. Cookies desencriptadas
    print("\n[3/4] Obteniendo cookies desencriptadas...")
    try:
        ss_data = http.get_json("/storage_state")
    except Exception as e:
        print(f"  ERROR descargando cookies: {e}")
        return
    n_cookies = len(ss_data.get("cookies", []))
    google_cookies = [c for c in ss_data.get("cookies", []) if "google" in (c.get("domain") or "")]
    has_sid = any(c["name"] in ("SID", "__Secure-1PSID") for c in google_cookies)
    print(f"  OK  {n_cookies} cookies ({len(google_cookies)} de Google)")
    if not has_sid:
        print("  [!] ADVERTENCIA: no hay tokens SID.")
    write_storage_state(ss_data, LOCAL_STATE_FILE)

    # ---- 4. Lanzar Chrome local
    print("\n[4/4] Iniciando Chrome local...")
    launcher = BrowserLauncher(DOWNLOADS_DIR)
    try:
        launcher.run(fp, ss_data, cache.dir, start_url)
    finally:
        if not args.no_lock:
            try:
                http.get_json(f"/unlock?client={client_id}")
                print("  Turno liberado.")
            except Exception:
                pass


if __name__ == "__main__":
    main()
