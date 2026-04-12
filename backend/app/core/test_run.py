import asyncio
import sys
from pathlib import Path

# Running this file directly does not put `backend` on sys.path; `app` lives there.
_backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_backend_root))

from app.core import DockerOrchestrator, SMOKE_DEPLOY


async def main():
    info = await DockerOrchestrator().deploy(SMOKE_DEPLOY)
    print(info)


asyncio.run(main())
