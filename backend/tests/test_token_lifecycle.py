from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth.api_tokens import create_api_token, get_user_by_api_token
from app.db.models import ApiToken


@pytest.mark.asyncio
async def test_expired_token_is_rejected(db_session_factory, seeded_user) -> None:
    async with db_session_factory() as session:
        _, minted = await create_api_token(
            session, seeded_user.id, "old",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        assert await get_user_by_api_token(session, minted.plaintext) is None


@pytest.mark.asyncio
async def test_valid_token_records_last_used(db_session_factory, seeded_user) -> None:
    async with db_session_factory() as session:
        record, minted = await create_api_token(session, seeded_user.id, "live")
        user = await get_user_by_api_token(session, minted.plaintext)
        assert user is not None
    async with db_session_factory() as session:
        stored = await session.get(ApiToken, record.id)
        assert stored is not None and stored.last_used_at is not None


def test_create_token_api_accepts_scope_and_expiry(api_client, seeded_user) -> None:
    response = api_client.post("/api/tokens/", json={
        "name": "cli", "scope": "read", "expires_in_days": 30,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "read"
    assert body["expires_at"] is not None


def test_read_scope_pat_is_read_only(api_client, seeded_user) -> None:
    """A read PAT can GET but not POST/DELETE; JWT and full-scope PATs are unaffected."""
    created = api_client.post("/api/tokens/", json={"name": "reader", "scope": "read"})
    assert created.status_code == 201
    read_pat = created.json()["token"]
    read_id = created.json()["id"]

    full_pat = api_client.post(
        "/api/tokens/", json={"name": "writer", "scope": "full"}
    ).json()["token"]

    def as_pat(value: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {value}"}

    assert api_client.get("/api/tokens/", headers=as_pat(read_pat)).status_code == 200
    assert (
        api_client.post(
            "/api/tokens/", json={"name": "blocked"}, headers=as_pat(read_pat)
        ).status_code
        == 403
    )
    assert (
        api_client.delete(f"/api/tokens/{read_id}", headers=as_pat(read_pat)).status_code
        == 403
    )

    assert api_client.get("/api/tokens/", headers=as_pat(full_pat)).status_code == 200
    assert (
        api_client.post(
            "/api/tokens/", json={"name": "allowed"}, headers=as_pat(full_pat)
        ).status_code
        == 201
    )
    assert (
        api_client.delete(f"/api/tokens/{read_id}", headers=as_pat(full_pat)).status_code
        == 204
    )
