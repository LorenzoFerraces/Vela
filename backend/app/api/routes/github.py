"""GitHub OAuth and resource routes.

Routes are split between two mounting prefixes for tidy URLs:

* ``/api/auth/github/{start,callback,status}`` and ``DELETE /api/auth/github``
  cover the OAuth dance and on/off state.
* ``/api/github/repos`` and ``/api/github/repos/{owner}/{repo}/branches`` proxy
  GitHub for the repo picker on the Containers page.

Both router groups live in this single module since they share helpers; they're
exposed as ``router_auth`` and ``router_resource`` for ``api/app.py`` to mount.
"""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    GitHubAuthorizeUrlResponse,
    GitHubBranchSummary,
    GitHubRepoSummary,
    GitHubStatusResponse,
)
from app.core.exceptions import (
    GitHubAccountAlreadyLinkedError,
    GitHubNotConnectedError,
    GitHubOAuthError,
)
from app.core.oauth import (
    build_authorize_url,
    decode_state,
    decrypt_identity_token,
    delete_github_identity,
    encode_state,
    exchange_code_for_token,
    fetch_github_user,
    get_github_identity,
    list_repo_branches,
    list_user_repos,
    load_config,
    revoke_user_grant,
    upsert_github_identity,
)
from app.db.models import User

router_auth = APIRouter()
router_resource = APIRouter()


# ---------------------------------------------------------------------------
# OAuth dance: start, callback, status, disconnect
# ---------------------------------------------------------------------------


@router_auth.get("/github/start", response_model=GitHubAuthorizeUrlResponse)
async def start_github_oauth(
    current_user: Annotated[User, Depends(get_current_user)],
) -> GitHubAuthorizeUrlResponse:
    """Build the GitHub authorize URL for the current user (SPA navigates to it)."""
    config = load_config()
    state = encode_state(current_user.id)
    return GitHubAuthorizeUrlResponse(
        authorize_url=build_authorize_url(config, state=state),
    )


@router_auth.get("/github/callback")
async def github_oauth_callback(
    session: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    """GitHub redirects the browser here after consent.

    On success: store the encrypted token and bounce back to the SPA's settings
    page with ``?github=connected``. On failure: bounce back with
    ``?github=error&reason=...``. We never raise an HTTPException here because
    that would leave the user on a JSON error page outside the SPA.
    """
    frontend_base = _frontend_base_url()
    target = f"{frontend_base.rstrip('/')}/settings"

    if error:
        return _redirect_with_error(target, error, error_description)

    if not code or not state:
        return _redirect_with_error(target, "missing_params")

    try:
        claims = decode_state(state)
        config = load_config()
        access_token, granted_scopes = await exchange_code_for_token(
            config, code=code, state=state
        )
        profile = await fetch_github_user(access_token)
        await upsert_github_identity(
            session,
            user_id=claims.user_id,
            profile=profile,
            access_token=access_token,
            scopes=granted_scopes,
        )
    except GitHubOAuthError as exc:
        return _redirect_with_error(target, exc.reason, str(exc))
    except GitHubAccountAlreadyLinkedError as exc:
        return _redirect_with_error(target, "account_already_linked", str(exc))
    except Exception as exc:  # noqa: BLE001 — convert anything else to a friendly redirect
        return _redirect_with_error(target, "callback_failed", str(exc))

    return RedirectResponse(url=f"{target}?github=connected", status_code=302)


@router_auth.get("/github/status", response_model=GitHubStatusResponse)
async def github_status(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubStatusResponse:
    identity = await get_github_identity(session, current_user.id)
    if identity is None:
        return GitHubStatusResponse(connected=False)
    return GitHubStatusResponse(
        connected=True,
        login=identity.username,
        avatar_url=identity.avatar_url,
        scopes=_split_scopes(identity.scopes),
        connected_at=identity.connected_at,
    )


@router_auth.delete("/github", status_code=204, response_model=None)
async def disconnect_github(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    identity = await delete_github_identity(session, current_user.id)
    if identity is None or identity.access_token_encrypted is None:
        return None
    try:
        token = decrypt_identity_token(identity)
        if token is not None:
            config = load_config()
            await revoke_user_grant(config, token)
    except Exception:  # noqa: BLE001 — best-effort revoke; local row is already gone
        return None
    return None


# ---------------------------------------------------------------------------
# Resource proxies: repos / branches
# ---------------------------------------------------------------------------


@router_resource.get("/repos", response_model=list[GitHubRepoSummary])
async def list_repos(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1, le=100),
    per_page: int = Query(default=30, ge=1, le=100),
) -> list[GitHubRepoSummary]:
    token = await _require_github_token(session, current_user)
    repos = await list_user_repos(token, query=q, page=page, per_page=per_page)
    return [
        GitHubRepoSummary(
            full_name=repo.full_name,
            default_branch=repo.default_branch,
            private=repo.private,
            html_url=repo.html_url,
            description=repo.description,
        )
        for repo in repos
        if repo.full_name
    ]


@router_resource.get(
    "/repos/{owner}/{repo}/branches",
    response_model=list[GitHubBranchSummary],
)
async def list_branches(
    owner: str,
    repo: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[GitHubBranchSummary]:
    token = await _require_github_token(session, current_user)
    names = await list_repo_branches(token, owner=owner, repo=repo)
    return [GitHubBranchSummary(name=name) for name in names]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_github_token(session: AsyncSession, user: User) -> str:
    identity = await get_github_identity(session, user.id)
    if identity is None:
        raise GitHubNotConnectedError()
    token = decrypt_identity_token(identity)
    if token is None:
        raise GitHubNotConnectedError(
            "GitHub access token is missing on the stored identity. Reconnect in Settings."
        )
    return token


def _frontend_base_url() -> str:
    raw = os.environ.get("VELA_FRONTEND_BASE_URL", "").strip()
    return raw or "http://localhost:5173"


def _split_scopes(raw: str | None) -> list[str]:
    if not raw:
        return []
    # GitHub returns scopes as a comma-separated list (sometimes with spaces).
    return [scope.strip() for scope in raw.split(",") if scope.strip()]


def _redirect_with_error(
    target: str, reason: str, message: str | None = None
) -> RedirectResponse:
    params: dict[str, str] = {"github": "error", "reason": reason}
    if message:
        params["message"] = message[:200]
    return RedirectResponse(url=f"{target}?{urlencode(params)}", status_code=302)
