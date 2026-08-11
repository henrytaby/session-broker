from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import settings
from app.core.logging import setup_logging
from app.infrastructure.crypto.storage_state_assembler import ChromeCookieRepository


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Desencripta perfil Chrome/Brave -> storage_state.json"
    )
    parser.add_argument(
        "--profile",
        default=str(settings.master_dir),
        help="Directorio del perfil (con Local State)",
    )
    parser.add_argument("--out", default="storage_state.json", help="Archivo de salida JSON")
    args = parser.parse_args()

    profile = Path(args.profile)
    out = Path(args.out)
    if not profile.is_absolute():
        profile = Path.cwd() / profile

    print("=" * 60)
    print("  DECRYPT_PROFILE  -  Chrome/Brave DPAPI -> storage_state.json")
    print("=" * 60)
    print(f"Perfil : {profile}")
    print(f"Salida : {out}\n")

    repo = ChromeCookieRepository()
    state = repo.get_storage_state(profile)
    repo.persist(state, out)

    cookies = state.cookies
    relevant = [c for c in cookies if "google" in c.domain]
    print(f"\n[OK] storage_state exportado a: {out}")
    print(f"     Total cookies: {len(cookies)}")
    print(f"     Cookies de Google: {len(relevant)}")
    google_hosts = sorted({c.domain for c in cookies if "google" in c.domain})
    if google_hosts:
        print("     Hosts de Google encontrados:")
        for h in google_hosts[:15]:
            print(f"       - {h}")
    has_sid = any(
        c.name in ("SID", "__Secure-1PSID", "SIDCC")
        for c in cookies
        if "google" in c.domain
    )
    if has_sid:
        print("     [!] Tokens de sesion SID presentes -> sesion valida")
    else:
        print("     [!] ADVERTENCIA: no se encontraron SID. Quizas no estas logueado en Google.")


if __name__ == "__main__":
    main()
