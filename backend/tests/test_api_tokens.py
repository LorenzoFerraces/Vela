from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ApiToken


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_token_returns_plaintext_once(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("token-owner@example.com")
    with TestClient(db_app) as client:
        response = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        )
    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("vela_pat_")
    assert body["prefix"] == body["token"][:16]
    assert body["name"] == "cli:test"
    assert body["id"]


def test_token_is_stored_hashed(
    db_app: Any, db_session_factory: Any, provision_user: Any
) -> None:
    import asyncio

    _, jwt = provision_user("hashed@example.com")
    with TestClient(db_app) as client:
        body = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        ).json()

    async def fetch() -> list[ApiToken]:
        async with db_session_factory() as session:
            result = await session.execute(select(ApiToken))
            return list(result.scalars())

    records = asyncio.run(fetch())
    assert len(records) == 1
    record = records[0]
    assert record.token_hash == hashlib.sha256(body["token"].encode()).hexdigest()
    assert record.token_prefix == body["prefix"]
    assert body["token"] not in (record.token_hash, record.token_prefix)


def test_list_tokens_hides_secrets(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("list@example.com")
    with TestClient(db_app) as client:
        client.post("/api/tokens/", json={"name": "one"}, headers=_auth(jwt))
        response = client.get("/api/tokens", headers=_auth(jwt))
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert set(items[0]) == {"id", "name", "prefix", "created_at"}


def test_revoke_removes_the_token(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("revoke@example.com")
    with TestClient(db_app) as client:
        created = client.post(
            "/api/tokens/", json={"name": "one"}, headers=_auth(jwt)
        ).json()
        response = client.delete(f"/api/tokens/{created['id']}", headers=_auth(jwt))
        remaining = client.get("/api/tokens", headers=_auth(jwt)).json()
    assert response.status_code == 204
    assert remaining == []


def test_cannot_revoke_another_users_token(
    db_app: Any, provision_user: Any
) -> None:
    _, owner_jwt = provision_user("owner@example.com")
    _, other_jwt = provision_user("other@example.com")
    with TestClient(db_app) as client:
        created = client.post(
            "/api/tokens/", json={"name": "one"}, headers=_auth(owner_jwt)
        ).json()
        response = client.delete(
            f"/api/tokens/{created['id']}", headers=_auth(other_jwt)
        )
    assert response.status_code == 404


def test_tokens_require_auth(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.get("/api/tokens/")
    assert response.status_code == 401


def test_pat_cannot_create_another_token(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("pat-mint@example.com")
    with TestClient(db_app) as client:
        pat = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        ).json()["token"]
        response = client.post(
            "/api/tokens/", json={"name": "second"}, headers=_auth(pat)
        )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "API tokens cannot create other tokens. Log in interactively."
    )


def test_pat_authenticates_like_a_jwt(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("pat-auth@example.com")
    with TestClient(db_app) as client:
        pat = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        ).json()["token"]
        me = client.get("/api/auth/me", headers=_auth(pat))
    assert me.status_code == 200
    assert me.json()["email"] == "pat-auth@example.com"


def test_revoked_pat_is_rejected(db_app: Any, provision_user: Any) -> None:
    _, jwt = provision_user("revoked@example.com")
    with TestClient(db_app) as client:
        created = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        ).json()
        client.delete(f"/api/tokens/{created['id']}", headers=_auth(jwt))
        me = client.get("/api/auth/me", headers=_auth(created["token"]))
    assert me.status_code == 401


def test_deactivated_user_pat_is_rejected(
    db_app: Any, db_session_factory: Any, provision_user: Any
) -> None:
    import asyncio

    from app.db.models import User

    user, jwt = provision_user("inactive@example.com")
    with TestClient(db_app) as client:
        pat = client.post(
            "/api/tokens/", json={"name": "cli:test"}, headers=_auth(jwt)
        ).json()["token"]

    async def deactivate() -> None:
        async with db_session_factory() as session:
            row = await session.get(User, user.id)
            assert row is not None
            row.is_active = False
            await session.commit()

    asyncio.run(deactivate())
    with TestClient(db_app) as client:
        me = client.get("/api/auth/me", headers=_auth(pat))
    assert me.status_code == 403
    assert me.json()["code"] == "account_deactivated"
