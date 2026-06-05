"""Run the Vela API with uvicorn (dev: reload on code changes)."""

from __future__ import annotations

import app.bootstrap_env  # noqa: F401 — .env before uvicorn imports the app module.

import uvicorn

if __name__ == "__main__":
    import os

    uvicorn_log_level = os.environ.get("VELA_LOG_LEVEL", "info").strip().lower()
    uvicorn.run(
        "app.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=uvicorn_log_level,
    )
