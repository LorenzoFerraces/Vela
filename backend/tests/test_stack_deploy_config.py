"""Stack deploy config wiring."""

from __future__ import annotations

import uuid

from app.core.stacks.deploy import _build_deploy_config
from app.db.models import Stack, StackService, User


def test_build_deploy_config_registers_service_name_as_network_alias() -> None:
    user = User(id=uuid.uuid4(), email="deploy@example.com")
    stack = Stack(
        id=uuid.uuid4(),
        name="Commit-y-me-voy",
        network_name="vela-stack-testnet",
        project_id=uuid.uuid4(),
    )
    service = StackService(
        service_name="postgres",
        source_kind="image",
        source_ref="postgres:16",
        git_branch=None,
        container_port=5432,
        env_vars={"POSTGRES_DB": "epersgeist"},
        command=None,
        public_route=False,
        depends_on=None,
        volumes=[],
    )
    config = _build_deploy_config(
        stack,
        service,
        "Commit-y-me-voy_postgres",
        user,
        image_tag="postgres:16",
    )
    assert config.network == "vela-stack-testnet"
    assert config.network_aliases == ["postgres"]
