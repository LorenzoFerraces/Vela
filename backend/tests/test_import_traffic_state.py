import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.db.models import TrafficRouteRecord
from import_traffic_state import import_traffic_state


@pytest.mark.asyncio
async def test_import_is_idempotent_and_regenerates_document(
    tmp_path, db_session_factory
) -> None:
    spec = RouteSpec(
        route_id=uuid4().hex,
        host="legacy.example",
        path_prefix="/",
        backend_servers=[BackendServer(host="web", port=80)],
        tls_enabled=False,
        entrypoints=["web"],
    )
    state_file = tmp_path / ".vela-traffic-state.json"
    state_file.write_text(
        json.dumps({"routes": [spec.model_dump(mode="json")]}), encoding="utf-8"
    )
    dynamic_file = tmp_path / "traefik-http.yml"

    assert await import_traffic_state(state_file, db_session_factory, dynamic_file) == 1
    assert await import_traffic_state(state_file, db_session_factory, dynamic_file) == 1

    async with db_session_factory() as session:
        rows = (await session.execute(select(TrafficRouteRecord))).scalars().all()
    assert len(rows) == 1
    assert "legacy.example" in dynamic_file.read_text(encoding="utf-8")
