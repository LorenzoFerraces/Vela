import asyncio
import uuid

import pytest

from app.core.deploy.secret_resolution import runtime_config_with_secrets
from app.core.models import DeployConfig
from app.core.secret_store import create_secret


def test_runtime_copy_is_resolved_but_original_keeps_reference(db_session_factory) -> None:
    user_id = uuid.uuid4()
    config = DeployConfig(image="nginx", name="web", env_vars={"DB": "secret://DB_URL@latest"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            await create_secret(session, owner_user_id=user_id, project_id=None, name="DB_URL", value="postgres://real")
            runtime = await runtime_config_with_secrets(session, config, owner_user_id=user_id, project_id=None)
            assert runtime.env_vars["DB"] == "postgres://real"
            assert config.env_vars["DB"] == "secret://DB_URL@latest"
    import asyncio
    asyncio.run(scenario())


def test_previews_reject_secret_references(db_session_factory) -> None:
    import asyncio

    from app.core.exceptions import PreviewSecretForbiddenError
    config = DeployConfig(image="nginx", env_vars={"DB": "secret://DB_URL"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            try:
                await runtime_config_with_secrets(session, config, owner_user_id=uuid.uuid4(), project_id=None, allow_secrets=False)
            except PreviewSecretForbiddenError:
                return
            raise AssertionError("expected PreviewSecretForbiddenError")
    asyncio.run(scenario())


def test_project_scoped_secret_resolves_only_in_its_project(db_session_factory) -> None:
    from app.core.exceptions import SecretNotFoundError

    project_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    config = DeployConfig(image="nginx", env_vars={"DB": "secret://DB_URL@latest"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            await create_secret(session, owner_user_id=None, project_id=project_id, name="DB_URL", value="postgres://project")
            runtime = await runtime_config_with_secrets(session, config, owner_user_id=owner_id, project_id=project_id)
            assert runtime.env_vars["DB"] == "postgres://project"
            assert config.env_vars["DB"] == "secret://DB_URL@latest"
            with pytest.raises(SecretNotFoundError):
                await runtime_config_with_secrets(session, config, owner_user_id=owner_id, project_id=None)
    asyncio.run(scenario())


def test_owner_scoped_secret_resolves_for_a_project_deploy(db_session_factory) -> None:
    owner_id = uuid.uuid4()
    config = DeployConfig(image="nginx", env_vars={"DB": "secret://DB_URL@latest"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            await create_secret(session, owner_user_id=owner_id, project_id=None, name="DB_URL", value="postgres://personal")
            runtime = await runtime_config_with_secrets(
                session, config, owner_user_id=owner_id, project_id=uuid.uuid4()
            )
            assert runtime.env_vars["DB"] == "postgres://personal"
    asyncio.run(scenario())


def test_secrets_api_is_write_only_and_scope_guarded(
    api_client, anonymous_client, other_user_client,
    seeded_user, seeded_other_user, db_session_factory,
) -> None:
    from app.db.models import ProjectMembership

    assert anonymous_client.get("/api/secrets/").status_code == 401

    created = api_client.post(
        "/api/secrets/", json={"name": "DB_URL", "value": "super-secret"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["has_value"] is True
    assert body["latest_version"] == 1
    assert "super-secret" not in created.text

    listing = api_client.get("/api/secrets/")
    assert [row["name"] for row in listing.json()] == ["DB_URL"]
    assert "super-secret" not in listing.text
    secret_id = body["id"]
    assert other_user_client.patch(
        f"/api/secrets/{secret_id}", json={"value": "x"}
    ).status_code == 404

    async def add_viewer() -> None:
        async with db_session_factory() as session:
            session.add(ProjectMembership(
                project_id=seeded_user.personal_project_id,
                user_id=seeded_other_user.id,
                role="viewer",
            ))
            await session.commit()

    asyncio.run(add_viewer())
    project_secret = api_client.post(
        "/api/secrets/",
        json={
            "name": "PROJECT_KEY",
            "value": "top-secret",
            "project_id": str(seeded_user.personal_project_id),
        },
    )
    assert project_secret.status_code == 201
    assert project_secret.json()["project_id"] == str(seeded_user.personal_project_id)
    assert "top-secret" not in project_secret.text
    viewer_listing = other_user_client.get("/api/secrets/")
    assert viewer_listing.status_code == 200
    assert "top-secret" not in viewer_listing.text
    assert other_user_client.patch(
        f"/api/secrets/{project_secret.json()['id']}", json={"value": "bad"}
    ).status_code == 403

    rotated = api_client.patch(
        f"/api/secrets/{secret_id}", json={"value": "new-value"}
    )
    assert rotated.status_code == 200
    assert rotated.json()["latest_version"] == 2
    assert "new-value" not in rotated.text
    assert api_client.delete(f"/api/secrets/{secret_id}").status_code == 204
