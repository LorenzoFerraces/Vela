"""Load ``backend/.env`` into the process environment.

Imported for side effects before the rest of ``app`` reads ``os.environ``.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
