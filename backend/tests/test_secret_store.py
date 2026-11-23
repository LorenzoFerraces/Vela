import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import SecretCreate
from app.core.exceptions import SecretNotFoundError, SecretVersionNotFoundError
from app.core.secret_store import (
    create_secret,
    parse_secret_reference,
    resolve_secret_reference,
    set_secret_value,
)
from app.core.security.secrets import encrypt_secret
from app.db.models import Secret, SecretVersion


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


def test_secret_name_matches_reference_grammar() -> None:
    assert SecretCreate(name="DB_URL.v2-1", value="x").name == "DB_URL.v2-1"
    with pytest.raises(ValidationError):
        SecretCreate(name="bad name", value="x")
    with pytest.raises(ValidationError):
        SecretCreate(name="bad/name", value="x")


@pytest.mark.asyncio
async def test_secret_version_uniqueness_is_enforced(db_session_factory) -> None:
    user_id = uuid.uuid4()
    async with db_session_factory() as session:
        secret = await create_secret(session, owner_user_id=user_id, project_id=None, name="UNIQUE", value="one")
    async with db_session_factory() as session:
        # create_secret already stored version 1.
        session.add(SecretVersion(secret_id=secret.id, version=1, value_encrypted=b"duplicate"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_set_secret_value_retries_version_race(
    db_session_factory, monkeypatch
) -> None:
    user_id = uuid.uuid4()

    from sqlalchemy import func as real_func
    from sqlalchemy import literal

    import app.core.secret_store as store

    async with db_session_factory() as session:
        secret = await create_secret(
            session, owner_user_id=user_id, project_id=None, name="RACE2", value="one"
        )
        # A competing rotation lands version 2 before our stale max() read commits.
        session.add(SecretVersion(
            secret_id=secret.id, version=2, value_encrypted=encrypt_secret("competitor")
        ))
        await session.commit()

        state = {"stale": True}

        class _FuncProxy:
            @staticmethod
            def max(column):
                if state["stale"]:
                    state["stale"] = False
                    return literal(0)  # stale max() taken before the competitor landed
                return real_func.max(column)

        monkeypatch.setattr(store, "func", _FuncProxy())

        version = await set_secret_value(session, secret, "three")
        assert version.version == 3
        assert state["stale"] is False

        versions = (await session.execute(
            select(SecretVersion.version).where(SecretVersion.secret_id == secret.id)
        )).scalars().all()
        assert sorted(versions) == [1, 2, 3]
