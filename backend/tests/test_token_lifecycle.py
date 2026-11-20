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
