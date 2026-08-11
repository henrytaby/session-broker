from __future__ import annotations

import argparse

from app.core.logging import setup_logging
from app.infrastructure.fingerprint.fingerprint import default_fingerprint


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="fingerprint.json")
    args = parser.parse_args()
    fp = default_fingerprint()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(fp.model_dump_json(indent=2))
    print(f"Huella guardada en {args.out}")
    print(f"  UA: {fp.user_agent}")
    print(f"  TZ: {fp.timezone}")
    print(f"  Screen: {fp.screen_width}x{fp.screen_height}")
    print(f"  WebGL: {fp.webgl_renderer}")


if __name__ == "__main__":
    main()
