from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ContainerLog, LogLevel, LogSource


def test_logs_requires_container_id(api_client: TestClient) -> None:
    """Requesting logs without container_id is rejected as 422."""
    response = api_client.get("/api/logs/")
    assert response.status_code == 422


def test_logs_invalid_level_is_422(api_client: TestClient) -> None:
    """An unknown level filter is rejected as 422."""
    response = api_client.get("/api/logs/?container_id=cid-1&level=NOT_A_LEVEL")
    assert response.status_code == 422


def test_logs_invalid_source_is_422(api_client: TestClient) -> None:
    """An unknown source filter is rejected as 422."""
    response = api_client.get("/api/logs/?container_id=cid-1&source=not-a-source")
    assert response.status_code == 422


def test_foreign_container_logs_are_forbidden(other_user_client: TestClient) -> None:
    """Querying logs of another user's container returns 404."""
    response = other_user_client.get("/api/logs/?container_id=cid-1")
    assert response.status_code == 404


def test_missing_container_logs_are_404(api_client: TestClient) -> None:
    """Logs for an unknown container id return 404."""
    response = api_client.get("/api/logs/?container_id=cid-nope")
    assert response.status_code == 404


def test_owner_can_query_container_logs(api_client: TestClient) -> None:
    """Owner gets an empty page for a container with no stored logs."""
    response = api_client.get(
        "/api/logs/?container_id=cid-1&level=info&source=stdout&limit=5"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["entries"] == []


def test_query_logs_with_entries(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    """Querying a container's logs returns both stored entries."""
    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="Started server",
        ),
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: connection refused",
        ),
    ]

    async def _insert() -> None:
        """Insert the fixture log rows and commit them."""
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/?container_id=cid-1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["entries"]) == 2


def test_query_logs_filter_by_level(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    """The level filter returns only entries with that level."""
    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: something failed",
        ),
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="info message",
        ),
    ]

    async def _insert() -> None:
        """Insert the fixture log rows and commit them."""
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/?container_id=cid-1&level=error")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    for entry in data["entries"]:
        assert entry["level"] == "error"


def test_query_logs_search(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    """The search term returns only entries whose message contains it."""
    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="User logged in",
        ),
        ContainerLog(
            container_id="cid-1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: connection refused",
        ),
    ]

    async def _insert() -> None:
        """Insert the fixture log rows and commit them."""
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/?container_id=cid-1&q=connection")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    for entry in data["entries"]:
        assert "connection" in entry["message"]


def test_export_logs_csv(api_client: TestClient) -> None:
    """Export returns a CSV body with the log header columns."""
    response = api_client.get("/api/logs/export?container_id=cid-1")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    content = response.text
    assert "timestamp" in content
    assert "container_id" in content


def test_export_logs_requires_container_id(api_client: TestClient) -> None:
    """Exporting without container_id is rejected as 422."""
    response = api_client.get("/api/logs/export")
    assert response.status_code == 422


def test_export_foreign_container_logs_are_forbidden(
    other_user_client: TestClient,
) -> None:
    """Exporting another user's container logs returns 404."""
    response = other_user_client.get("/api/logs/export?container_id=cid-1")
    assert response.status_code == 404
