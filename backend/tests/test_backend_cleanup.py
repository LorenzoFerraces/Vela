import uuid

from fastapi.testclient import TestClient

from app.core.llm.cache import cache_identity
from app.core.llm.provider import DEFAULT_LLM_MODEL


def test_single_default_llm_model() -> None:
    assert DEFAULT_LLM_MODEL == "gemini-3.1-flash-lite"


def test_cache_identity_separates_users_and_repos() -> None:
    user = uuid.uuid4()
    from app.core.llm.provider import LlmConfig

    config = LlmConfig(
        provider="gemini", url="https://example.test", headers={},
        params={}, model="m",
    )
    assert cache_identity(user, config, "repo-a") != cache_identity(user, config, "repo-b")
    assert cache_identity(user, config, "repo-a") != cache_identity(uuid.uuid4(), config, "repo-a")


def test_viewer_cannot_update_scaling_policy(
    api_client: TestClient, seeded_user, seeded_other_user, fake_orchestrator,
    db_session_factory,
) -> None:
    import asyncio

    from app.core.auth.tokens import create_access_token
    from app.core.models import ContainerInfo, ContainerStatus
    from app.db.models import ProjectMembership

    async def prepare() -> None:
        async with db_session_factory() as session:
            session.add(ProjectMembership(
                project_id=seeded_user.personal_project_id,
                user_id=seeded_other_user.id, role="viewer",
            ))
            await session.commit()

    asyncio.run(prepare())
    fake_orchestrator.seed_container(ContainerInfo.model_validate({
        "id": "scale-cid", "name": "api", "image": "nginx",
        "status": ContainerStatus.RUNNING, "created_at": "2026-04-01T12:00:00+00:00",
        "labels": {"vela.project_id": str(seeded_user.personal_project_id)},
        "ports": [],
    }))

    api_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_other_user.id)}"
    response = api_client.put("/api/scaling/policies/api", json={"enabled": True})
    assert response.status_code == 403
