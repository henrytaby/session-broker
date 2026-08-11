"""Thin shim preserving the documented CLI (AGENTS.md).

Delegates to app.infrastructure.crypto.cli. The real implementation now lives
in app/infrastructure/crypto/* (DPAPI + AES-GCM + SQLite + assembler).

Uso:
    python decrypt_profile.py --profile C:\\chrome-sessions\\master --out storage_state.json
    python decrypt_profile.py                       # rutas por defecto
"""
from app.infrastructure.crypto.cli import main

if __name__ == "__main__":
    main()
