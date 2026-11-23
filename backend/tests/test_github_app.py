"""GitHub App signature verification and installation token helpers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import github_app
from app.core.deploy import github_auth
from app.core.exceptions import GitHubAppNotConfiguredError
from app.core.security.secrets import encrypt_secret
from app.db.models import GitHubAppInstall, GitHubAppInstallationId


def _signature(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def test_verify_github_signature_accepts_valid_digest() -> None:
    payload = b'{"ref":"refs/heads/main"}'
    assert (
        github_app.verify_github_signature(payload, "hook-secret", _signature(payload, "hook-secret"))
        is True
    )


@pytest.mark.parametrize("signature", [None, "bad", "md5=abc", "sha256=wrong"])
def test_verify_github_signature_rejects_bad_digest(
    signature: str | None,
) -> None:
    assert github_app.verify_github_signature(b"{}", "hook-secret", signature) is False


def test_installation_token_posts_signed_jwt(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid.uuid4()
    pem = _rsa_pem()

    async def seed() -> None:
        async with db_session_factory() as session:
            install = GitHubAppInstall(
                app_id="12345",
                private_key_encrypted=encrypt_secret(pem),
                webhook_secret_encrypted=encrypt_secret("hook-secret"),
            )
            session.add(install)
            await session.flush()
            session.add(
                GitHubAppInstallationId(
                    app_install_id=install.id,
                    project_id=project_id,
                    installation_id="987",
                )
            )
            await session.commit()

    asyncio.run(seed())

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"token": "ghs_installation_token"})

    original = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(github_app.httpx, "AsyncClient", patched_client)

    async def call() -> str:
        async with db_session_factory() as session:
            return await github_app.installation_token(session, project_id)

    assert asyncio.run(call()) == "ghs_installation_token"
    assert len(requests) == 1
    assert requests[0].url.path == "/app/installations/987/access_tokens"
    assertion = requests[0].headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(assertion, options={"verify_signature": False})
    assert claims["iss"] == "12345"
    assert claims["exp"] - claims["iat"] == 600


def test_installation_token_requires_app_config(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def call() -> None:
        async with db_session_factory() as session:
            await github_app.installation_token(session, uuid.uuid4())

    with pytest.raises(GitHubAppNotConfiguredError):
        asyncio.run(call())


def test_installation_token_requires_installation_link(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="12345",
                    private_key_encrypted=encrypt_secret(_rsa_pem()),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            await session.commit()

    asyncio.run(seed())

    async def call() -> None:
        async with db_session_factory() as session:
            await github_app.installation_token(session, uuid.uuid4())

    with pytest.raises(GitHubAppNotConfiguredError):
        asyncio.run(call())


def test_project_token_prefers_installation_token(
    db_session_factory: async_sessionmaker[AsyncSession],
    seeded_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def app_token(_session: AsyncSession, _project_id: uuid.UUID) -> str:
        return "ghs_app_token"

    monkeypatch.setattr(github_auth, "installation_token", app_token)

    async def call() -> str | None:
        async with db_session_factory() as session:
            return await github_auth.github_token_for_project(
                session, uuid.uuid4(), seeded_user
            )

    assert asyncio.run(call()) == "ghs_app_token"


def test_project_token_falls_back_to_pat(
    db_session_factory: async_sessionmaker[AsyncSession],
    seeded_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_app(_session: AsyncSession, _project_id: uuid.UUID) -> str:
        raise GitHubAppNotConfiguredError("not configured")

    async def pat(_session: AsyncSession, _user: Any, _source: str) -> str:
        return "ghp_user_token"

    monkeypatch.setattr(github_auth, "installation_token", no_app)
    monkeypatch.setattr(github_auth, "github_token_for_url", pat)

    async def call() -> str | None:
        async with db_session_factory() as session:
            return await github_auth.github_token_for_project(
                session, uuid.uuid4(), seeded_user
            )

    assert asyncio.run(call()) == "ghp_user_token"
