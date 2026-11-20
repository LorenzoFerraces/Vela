from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.deploy.deployment_history import (
    DeploymentSnapshot,
    load_deploy_config_snapshot,
    record_deployment,
)
from app.core.models import ContainerInfo, ContainerStatus, DeployConfig
from app.core.scaling.scaling_engine import _base_container_info, build_replica_config


def test_replica_config_preserves_env_command_limits_and_network() -> None:
    config = DeployConfig(
        image="nginx:alpine", name="api", container_port=8080,
        env_vars={"MODE": "prod"}, command=["nginx", "-g", "daemon off;"],
        cpu_limit=0.5, memory_limit=256, labels={"vela.project_id": "p1"},
    )
    replica = build_replica_config(config, 2)
    assert replica.image == "nginx:alpine"
    assert replica.env_vars == {"MODE": "prod"}
    assert replica.command == ["nginx", "-g", "daemon off;"]
    assert replica.cpu_limit == 0.5
    assert replica.memory_limit == 256
    assert replica.labels == config.labels
    assert replica.name == "api-r2"


def test_deploy_config_snapshot_round_trip(db_session_factory, seeded_user) -> None:
    import asyncio

    config = DeployConfig(image="nginx:alpine", name="api", container_port=80, env_vars={"A": "B"})

    async def run() -> None:
        async with db_session_factory() as session:
            await record_deployment(
                session, user_id=seeded_user.id,
                project_id=seeded_user.personal_project_id,
                snapshot=DeploymentSnapshot(
                    container_id="cid-snap", container_name="api",
                    source_kind="image", source_ref="nginx:alpine", git_branch=None,
                    image_tag="nginx:alpine", container_port=80,
                    env_vars={}, command=None, dockerfile_snapshot=None, public_url=None,
                    deploy_config=config.model_dump(mode="json"),
                ),
            )
        async with db_session_factory() as session:
            loaded = await load_deploy_config_snapshot(session, "cid-snap")
            assert loaded is not None
            assert loaded.env_vars["A"] == "B"
            # The lookup is keyed by Docker id; the policy's name must not match.
            assert await load_deploy_config_snapshot(session, "api") is None

    asyncio.run(run())


def test_base_container_info_resolves_policy_name_to_docker_id(
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    import asyncio

    info = ContainerInfo.model_validate({
        "id": "cid-real", "name": "api", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00", "labels": {}, "ports": [],
    })
    fake_orchestrator.seed_container(info)
    resolved = asyncio.run(_base_container_info(fake_orchestrator, "api"))
    assert resolved is not None
    assert resolved.id == "cid-real"
