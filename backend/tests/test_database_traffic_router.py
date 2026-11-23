from uuid import uuid4

import pytest

from app.core.traffic.database_traffic_router import DatabaseTrafficRouter
from app.core.traffic.traffic_models import BackendServer, RouteSpec


@pytest.fixture
def router(tmp_path, db_session_factory):
    return DatabaseTrafficRouter(
        session_factory=db_session_factory,
        traefik_dynamic_file=tmp_path / "traefik-http.yml",
    )


def _spec(host: str) -> RouteSpec:
    return RouteSpec(
        route_id=uuid4().hex,
        host=host,
        path_prefix="/",
        backend_servers=[BackendServer(host="web", port=80)],
        tls_enabled=False,
        entrypoints=["web"],
    )


@pytest.mark.asyncio
async def test_upsert_get_remove_round_trip(router) -> None:
    spec = _spec("web.example")
    info = await router.upsert_route(spec)
    assert info.route_id == spec.route_id
    assert (await router.get_route(spec.route_id)).host == "web.example"
    assert len(await router.list_routes()) == 1
    await router.remove_route(spec.route_id)
    assert await router.list_routes() == []


@pytest.mark.asyncio
async def test_upsert_regenerates_traefik_document(router) -> None:
    spec = _spec("web.example")
    await router.upsert_route(spec)
    content = router.traefik_dynamic_file.read_text(encoding="utf-8")
    assert "web.example" in content
