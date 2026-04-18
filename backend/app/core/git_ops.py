"""Git helpers for shallow clones (used by API and image builder)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from app.core.exceptions import CloneError


async def git_shallow_clone(*, url: str, branch: str, dest: Path) -> None:
    """Clone ``url`` into ``dest`` (``dest`` must not exist yet)."""

    def _run() -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    url,
                    str(dest),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except FileNotFoundError as e:
            raise CloneError(
                url, "git executable not found — install Git and ensure it is on PATH."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise CloneError(url, "git clone timed out after 600s.") from e

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise CloneError(url, err)

    await asyncio.to_thread(_run)


def rm_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
