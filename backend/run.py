"""Run the Vela API with uvicorn (dev: reload on code changes)."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
