import uuid
import pytest
from app.core.exceptions import SecretNotFoundError, SecretVersionNotFoundError
from app.core.secret_store import create_secret, parse_secret_reference, resolve_secret_reference, set_secret_value
from app.db.models import Secret


@pytest.mark.asyncio
async def test_write_only_versions_and_resolution(db_session_factory) -> None:
    user_id = uuid.uuid4()
    async with db_session_factory() as session:
        secret: Secret = await create_secret(session, owner_user_id=user_id, project_id=None, name="DB_URL", value="postgres://one")
        first = await set_secret_value(session, secret, "postgres://two")
        assert first.version == 2
        assert await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="DB_URL", version="1") == "postgres://one"
        assert await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="DB_URL", version="latest") == "postgres://two"
        with pytest.raises(SecretVersionNotFoundError):
            await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="DB_URL", version="99")


@pytest.mark.asyncio
async def test_missing_secret_and_version_are_actionable(db_session_factory) -> None:
    user_id = uuid.uuid4()
    async with db_session_factory() as session:
        with pytest.raises(SecretNotFoundError):
            await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="MISSING", version="latest")


def test_reference_pattern() -> None:
    assert parse_secret_reference("secret://DB_URL@2") == ("DB_URL", "2")
    assert parse_secret_reference("plain-value") is None
