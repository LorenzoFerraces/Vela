"""Load ``backend/.env`` into the process environment.

Imported for side effects before the rest of ``app`` reads ``os.environ``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")


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
