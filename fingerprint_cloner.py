"""Thin shim preserving the documented CLI (AGENTS.md).

Delegates to app.infrastructure.fingerprint.cli. The real implementation now
lives in app/infrastructure/fingerprint/* (Fingerprint model + builders +
init_script). Backwards-compatible imports are also re-exported below.

Uso:
    python fingerprint_cloner.py --out fingerprint.json
    from fingerprint_cloner import Fingerprint, build_chromium_args, build_context_opts
"""
from app.domain.models import Fingerprint
from app.infrastructure.fingerprint.chrome_finder import (
    detect_chrome_version,
    detect_webgl_renderer,
)
from app.infrastructure.fingerprint.cli import main
from app.infrastructure.fingerprint.fingerprint import (
    build_chromium_args,
    build_context_opts,
    default_fingerprint,
    init_script,
)

# Backwards-compat: v9 code expected Fingerprint.default() / .to_json() / .init_script()
Fingerprint.default = staticmethod(default_fingerprint)  # type: ignore[attr-defined]
Fingerprint.to_json = lambda self: self.model_dump_json(indent=2)  # type: ignore[attr-defined]
Fingerprint.from_json = classmethod(lambda cls, s: cls.model_validate_json(s))  # type: ignore[attr-defined]
Fingerprint.init_script = init_script  # type: ignore[attr-defined]

__all__ = [
    "Fingerprint",
    "build_chromium_args",
    "build_context_opts",
    "init_script",
    "default_fingerprint",
    "detect_chrome_version",
    "detect_webgl_renderer",
    "main",
]

if __name__ == "__main__":
    main()
