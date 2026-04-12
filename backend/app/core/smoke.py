"""Hardcoded deploy configuration for local manual verification with Docker.

Example::

    import asyncio
    from app.core.docker_orchestrator import DockerOrchestrator
    from app.core.smoke import SMOKE_DEPLOY

    async def main() -> None:
        orch = DockerOrchestrator()
        info = await orch.deploy(SMOKE_DEPLOY)
        print(info)

    asyncio.run(main())

Then open http://127.0.0.1:18080 (host port mapped to nginx port 80).
The orchestrator adds the ``vela.managed`` label; do not set it here.
"""

from app.core.models import DeployConfig, PortMapping

SMOKE_DEPLOY = DeployConfig(
    image="nginx:alpine",
    name="vela-smoke",
    ports=[PortMapping(host_port=18080, container_port=80)],
)
