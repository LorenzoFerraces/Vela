"""Load env files into the process environment.

Imported for side effects before the rest of ``app`` reads ``os.environ``.

Precedence (highest first): process environment, ``backend/.env`` (optional
dev overrides), repo-root ``.env`` (official config; docker compose reads it).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
# Both loads use override=False: real process env (tests, E2E, compose) always wins.
# ``backend/.env`` loads first so its keys win over the root file for direct runs.
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")


def _configure_app_logging() -> None:
    """Send ``app.*`` log records to stderr (uvicorn only configures its own loggers)."""
    if os.environ.get("VELA_CONFIGURE_LOGGING", "1").strip() == "0":
        return

    level_name = os.environ.get("VELA_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


_configure_app_logging()
