"""Git helpers for shallow clones (used by API and image builder)."""

from __future__ import annotations

import asyncio
import base64
import re
import shutil
import subprocess
from pathlib import Path

from app.core.exceptions import CloneError

_CREDENTIALS_IN_URL = re.compile(r"(https?://)([^/@:\s]+:)?[^/@\s]+@", re.IGNORECASE)


async def git_shallow_clone(
    *,
    url: str,
    branch: str,
    dest: Path,
    access_token: str | None = None,
) -> None:
    """Clone ``url`` into ``dest`` (``dest`` must not exist yet).

    When ``access_token`` is provided and ``url`` is HTTPS, the token is sent
    via ``http.extraheader`` so it never appears in the URL, in process listings
    (``ps``), or in any error message. Errors are sanitized to mask credentials
    that callers might have embedded in the URL themselves.
    """

    cmd = _build_clone_command(url=url, branch=branch, dest=dest, access_token=access_token)

    def _run() -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except FileNotFoundError as exc:
            raise CloneError(
                _sanitize_url(url),
                "git executable not found — install Git and ensure it is on PATH.",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CloneError(
                _sanitize_url(url), "git clone timed out after 600s."
            ) from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise CloneError(_sanitize_url(url), _sanitize_message(err))

    await asyncio.to_thread(_run)


def _build_clone_command(
    *,
    url: str,
    branch: str,
    dest: Path,
    access_token: str | None,
) -> list[str]:
    cmd: list[str] = ["git"]
    if access_token and url.lower().startswith("https://"):
        # Send credentials via header so the URL stays clean. ``x-access-token``
        # is GitHub's documented username for OAuth/PAT Basic auth.
        token_pair = f"x-access-token:{access_token}".encode("utf-8")
        encoded = base64.b64encode(token_pair).decode("ascii")
        cmd.extend(["-c", f"http.extraheader=Authorization: Basic {encoded}"])
    cmd.extend(
        [
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            url,
            str(dest),
        ]
    )
    return cmd


def _sanitize_url(url: str) -> str:
    """Mask any ``user:password@`` segment that callers might have embedded in the URL."""
    return _CREDENTIALS_IN_URL.sub(r"\1***@", url)


def _sanitize_message(message: str) -> str:
    return _CREDENTIALS_IN_URL.sub(r"\1***@", message)


def rm_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
