"""Audit log emission for admin route and image host operations."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.db.models import AuditLog


def test_admin_route_and_image_actions_emit_audit_entries(
    make_authed_client,
    provision_user,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    admin, admin_token = provision_user("audit-host-admin@example.com", role="admin")
    spec = RouteSpec(
        route_id="audited-route",
        host="app.example.test",
        path_prefix="/",
        backend_servers=[BackendServer(host="nginx", port=80)],
        tls_enabled=False,
    )

    with make_authed_client() as client:
        client.headers["Authorization"] = f"Bearer {admin_token}"
        assert client.post("/api/routes", json=spec.model_dump(mode="json")).status_code == 200
        assert client.post(
            "/api/images/pull", params={"image": "nginx", "tag": "alpine"}
        ).status_code == 200

    async def load_entries() -> list[AuditLog]:
        async with db_session_factory() as session:
            result = await session.execute(
                select(AuditLog).where(AuditLog.user_id == admin.id)
            )
            return list(result.scalars().all())

    entries = asyncio.run(load_entries())
    actions = {entry.action for entry in entries}
    assert "route.upsert" in actions
    assert "image.pull" in actions
    assert all(entry.user_id == admin.id for entry in entries)
