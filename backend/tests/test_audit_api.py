from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.service import emit_audit_log


TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


async def _emit(
    factory: async_sessionmaker[AsyncSession],
    action: str,
    target_type: str,
    target_id: str = "cid-1",
) -> None:
    async with factory() as session:
        await emit_audit_log(session, TEST_USER_ID, action, target_type, target_id)
        await session.commit()


def test_get_audit_log_returns_200(api_client: TestClient) -> None:
    response = api_client.get("/api/audit/log")
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data
    assert "total" in data
    assert isinstance(data["entries"], list)


def test_get_audit_log_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/audit/log")
    assert response.status_code == 401


def test_get_audit_log_filter_by_action(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        await _emit(db_session_factory, "container.deploy", "container", "cid-1")
        await _emit(db_session_factory, "container.start", "container", "cid-2")
        await _emit(db_session_factory, "container.deploy", "container", "cid-3")

    asyncio.run(run())

    response = api_client.get("/api/audit/log", params={"action": "container.deploy"})
    assert response.status_code == 200
    data = response.json()
    assert all(e["action"] == "container.deploy" for e in data["entries"])
    assert data["total"] == 2


def test_get_audit_log_filter_by_target_type(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        await _emit(db_session_factory, "container.deploy", "container", "cid-1")
        await _emit(db_session_factory, "user.login", "user", str(TEST_USER_ID))

    asyncio.run(run())

    response = api_client.get("/api/audit/log", params={"target_type": "container"})
    assert response.status_code == 200
    data = response.json()
    assert all(e["target_type"] == "container" for e in data["entries"])
    assert data["total"] == 1


def test_get_audit_log_pagination(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        for i in range(5):
            await _emit(db_session_factory, f"action.{i}", "container", f"cid-{i}")

    asyncio.run(run())

    page1 = api_client.get("/api/audit/log", params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    assert len(page1.json()["entries"]) == 2
    assert page1.json()["total"] == 5

    page2 = api_client.get("/api/audit/log", params={"limit": 2, "offset": 2})
    assert page2.status_code == 200
    assert len(page2.json()["entries"]) == 2

    page3 = api_client.get("/api/audit/log", params={"limit": 2, "offset": 4})
    assert page3.status_code == 200
    assert len(page3.json()["entries"]) == 1
