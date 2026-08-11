from __future__ import annotations

import argparse

import uvicorn

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.infrastructure.api.server import create_app
from app.infrastructure.profile.chrome_process import (
    refresh_master_to_instances,
    setup_firewall,
)

log = get_logger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Session Sharing Server (v9 clean arch)")
    parser.add_argument("--instances", type=int, default=None, help="N instancias Chrome headless")
    parser.add_argument("--refresh", action="store_true", help="Recopiar master a instancias")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _parse_args(argv if argv is not None else _raw_argv())

    if args.instances is not None:
        settings.CHROME_INSTANCES = max(0, args.instances)

    if args.refresh and settings.CHROME_INSTANCES > 0:
        log.info("Modo: copia desde master")
        refresh_master_to_instances()

    setup_firewall()

    ai_session = None
    if settings.CHROME_INSTANCES > 0:
        from app.infrastructure.chat.gemini_cdp_session import GeminiCdpSession

        ai_session = GeminiCdpSession()

    app = create_app(ai_session=ai_session)

    log.info("=" * 65)
    log.info("SERVIDOR LISTO  (host=%s port=%d instancias=%d)", settings.API_HOST, settings.API_PORT, settings.CHROME_INSTANCES)
    log.info("  Chat frontend   -> http://127.0.0.1:%d/", settings.API_PORT)
    log.info("  Health          -> http://127.0.0.1:%d/health", settings.API_PORT)
    log.info("  storage_state   -> http://127.0.0.1:%d/storage_state?token=***", settings.API_PORT)
    log.info("=" * 65)

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, log_level=settings.LOG_LEVEL.lower())


def _raw_argv() -> list[str]:
    import sys

    return sys.argv[1:]


if __name__ == "__main__":
    main()
