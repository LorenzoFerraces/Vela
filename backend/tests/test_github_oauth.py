"""Tests for the GitHub OAuth flow (start / callback / status / disconnect / repos / branches).

External HTTP calls to github.com / api.github.com are routed through an
``httpx.MockTransport`` so the suite stays offline. Only this module needs the
optional encryption key, and it sets one for the whole file.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.oauth import github as github_oauth
from app.core.oauth.identity import GITHUB_PROVIDER, decrypt_identity_token
from app.core.oauth.state import encode_state
from app.core.security import reset_token_cipher_for_tests
from app.core.security.secrets import encrypt_secret
from app.db.models import User, UserOAuthIdentity


@pytest.fixture(autouse=True)
def github_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("VELA_GITHUB_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("VELA_GITHUB_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv(
        "VELA_GITHUB_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/github/callback",
    )
    monkeypatch.setenv("VELA_GITHUB_OAUTH_SCOPES", "repo,read:user")
    monkeypatch.setenv("VELA_FRONTEND_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("VELA_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_token_cipher_for_tests()
    yield
    reset_token_cipher_for_tests()


# ---------------------------------------------------------------------------
# httpx mocking
# ---------------------------------------------------------------------------


class _RecordingTransport(httpx.MockTransport):
    """``MockTransport`` that records every request for assertions."""

    def __init__(self, handler):
        self.requests: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(wrapped)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> _RecordingTransport:
    transport = _RecordingTransport(handler)
    original = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(github_oauth.httpx, "AsyncClient", patched_async_client)
    return transport


# ---------------------------------------------------------------------------
# Start: builds a GitHub authorize URL
# ---------------------------------------------------------------------------


def test_start_returns_authorize_url(api_client: TestClient) -> None:
    response = api_client.get("/api/auth/github/start")
    assert response.status_code == 200
    body = response.json()
    url = body["authorize_url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-id-test" in url
    assert "scope=repo+read%3Auser" in url
    assert "state=" in url


def test_start_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/auth/github/start")
    assert response.status_code == 401


def test_start_missing_config_returns_503(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VELA_GITHUB_CLIENT_ID", raising=False)
    response = api_client.get("/api/auth/github/start")
    assert response.status_code == 503
    assert "VELA_GITHUB_CLIENT_ID" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Callback: token exchange + identity upsert + redirect
# ---------------------------------------------------------------------------


def test_callback_persists_identity_and_redirects(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = encode_state(seeded_user.id)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login/oauth/access_token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "ghp_real_token_value",
                    "scope": "repo,read:user",
                    "token_type": "bearer",
                },
            )
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={"id": 99, "login": "octocat", "avatar_url": "https://gh/u/99.png"},
            )
        return httpx.Response(404, json={"message": "not handled"})

    _install_transport(monkeypatch, handler)

    response = api_client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "http://localhost:5173/settings?github=connected"
    )

    import asyncio

    async def fetch() -> UserOAuthIdentity | None:
        async with db_session_factory() as session:
            return await session.scalar(
                select(UserOAuthIdentity).where(
                    UserOAuthIdentity.user_id == seeded_user.id,
                    UserOAuthIdentity.provider == GITHUB_PROVIDER,
                )
            )

    identity = asyncio.run(fetch())
    assert identity is not None
    assert identity.username == "octocat"
    assert identity.provider_subject == "99"
    assert identity.scopes == "repo,read:user"
    assert identity.access_token_encrypted is not None
    assert decrypt_identity_token(identity) == "ghp_real_token_value"


def test_callback_with_invalid_state_redirects_with_error(
    api_client: TestClient,
) -> None:
    response = api_client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": "not-a-valid-jwt"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://localhost:5173/settings?")
    assert "github=error" in location
    assert "reason=invalid_state" in location


def test_callback_with_provider_error_redirects_with_reason(
    api_client: TestClient,
) -> None:
    response = api_client.get(
        "/api/auth/github/callback",
        params={"error": "access_denied", "error_description": "User cancelled"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "github=error" in location
    assert "reason=access_denied" in location


def test_callback_token_exchange_failure_redirects_with_error(
    api_client: TestClient,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = encode_state(seeded_user.id)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login/oauth/access_token"):
            return httpx.Response(
                200,
                json={
                    "error": "bad_verification_code",
                    "error_description": "The code is bad.",
                },
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    response = api_client.get(
        "/api/auth/github/callback",
        params={"code": "expired", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "reason=bad_verification_code" in location


def test_callback_when_github_subject_belongs_to_another_user_redirects(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    seeded_other_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``uq_oauth_provider_subject``: same GitHub user id cannot link two Vela accounts."""
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_existing")
    state = encode_state(seeded_other_user.id)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login/oauth/access_token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "ghp_new",
                    "scope": "repo",
                    "token_type": "bearer",
                },
            )
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={"id": 99, "login": "octocat", "avatar_url": None},
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    response = api_client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "github=error" in location
    assert "reason=account_already_linked" in location


# ---------------------------------------------------------------------------
# Status / disconnect / repos / branches
# ---------------------------------------------------------------------------


def test_status_disconnected_by_default(api_client: TestClient) -> None:
    response = api_client.get("/api/auth/github/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "connected": False,
        "login": None,
        "avatar_url": None,
        "scopes": [],
        "connected_at": None,
    }


def test_status_when_connected_reports_login_and_scopes(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
) -> None:
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_value")

    response = api_client.get("/api/auth/github/status")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["login"] == "octocat"
    assert body["scopes"] == ["repo", "read:user"]
    assert body["connected_at"] is not None


def test_disconnect_removes_identity(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_value")

    revoke_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        revoke_calls.append(request)
        return httpx.Response(204)

    _install_transport(monkeypatch, handler)

    response = api_client.delete("/api/auth/github")
    assert response.status_code == 204
    # GitHub revoke endpoint should have been hit best-effort.
    assert any(r.url.path.endswith("/grant") for r in revoke_calls)

    # Now status should report disconnected.
    status_resp = api_client.get("/api/auth/github/status")
    assert status_resp.json()["connected"] is False


def test_repos_requires_github_connection(api_client: TestClient) -> None:
    response = api_client.get("/api/github/repos")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "github_not_connected"


def test_repos_proxies_github_search_and_returns_slim_shape(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_value")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "octocat/Hello-World",
                        "default_branch": "main",
                        "private": False,
                        "html_url": "https://github.com/octocat/Hello-World",
                        "description": "first repo",
                    },
                    {
                        "full_name": "octocat/private",
                        "default_branch": "trunk",
                        "private": True,
                        "html_url": "https://github.com/octocat/private",
                        "description": None,
                    },
                ],
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    response = api_client.get("/api/github/repos")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["full_name"] == "octocat/Hello-World"
    assert body[1]["private"] is True
    assert body[1]["default_branch"] == "trunk"


def test_branches_proxies_github(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_value")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/branches"):
            return httpx.Response(
                200,
                json=[{"name": "main"}, {"name": "develop"}],
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    response = api_client.get("/api/github/repos/octo/repo/branches")
    assert response.status_code == 200
    assert response.json() == [{"name": "main"}, {"name": "develop"}]


def test_repos_when_token_unauthorized_returns_502(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_identity(db_session_factory, seeded_user.id, token="ghp_revoked")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    _install_transport(monkeypatch, handler)

    response = api_client.get("/api/github/repos")
    assert response.status_code == 502
    assert "reconnect" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_identity(
    db_session_factory: async_sessionmaker,
    user_id: uuid.UUID,
    *,
    token: str,
) -> None:
    import asyncio

    async def run() -> None:
        async with db_session_factory() as session:
            session.add(
                UserOAuthIdentity(
                    user_id=user_id,
                    provider=GITHUB_PROVIDER,
                    provider_subject="99",
                    username="octocat",
                    avatar_url="https://gh/u/99.png",
                    scopes="repo,read:user",
                    access_token_encrypted=encrypt_secret(token),
                )
            )
            await session.commit()

    asyncio.run(run())
