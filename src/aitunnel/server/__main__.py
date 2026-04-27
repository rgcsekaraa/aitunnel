"""Entry point for `aitunnel-server` (and `python -m aitunnel.server`)."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    # Import here so the FastAPI app builds after env is loaded.
    from .app import build_app

    app = build_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )


if __name__ == "__main__":
    sys.exit(main())
