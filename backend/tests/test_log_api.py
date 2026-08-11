from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ContainerLog, LogLevel, LogSource


def test_query_logs_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/logs/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["entries"] == []


def test_query_logs_with_entries(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    import asyncio

    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="Started server",
        ),
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: connection refused",
        ),
    ]

    async def _insert() -> None:
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["entries"]) == 2


def test_query_logs_filter_by_level(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    import asyncio

    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: something failed",
        ),
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="info message",
        ),
    ]

    async def _insert() -> None:
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/?level=error")
    assert response.status_code == 200
    data = response.json()
    for entry in data["entries"]:
        assert entry["level"] == "error"


def test_query_logs_search(
    api_client: TestClient,
    db_session_factory: async_sessionmaker,
) -> None:
    import asyncio

    now = datetime.now(timezone.utc)
    logs = [
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDOUT,
            level=LogLevel.INFO,
            message="User logged in",
        ),
        ContainerLog(
            container_id="test-c1",
            container_name="my-app",
            timestamp=now,
            source=LogSource.STDERR,
            level=LogLevel.ERROR,
            message="ERROR: connection refused",
        ),
    ]

    async def _insert() -> None:
        async with db_session_factory() as session:
            session.add_all(logs)
            await session.commit()

    asyncio.run(_insert())

    response = api_client.get("/api/logs/?q=connection")
    assert response.status_code == 200
    data = response.json()
    for entry in data["entries"]:
        assert "connection" in entry["message"]


def test_export_logs_csv(api_client: TestClient) -> None:
    response = api_client.get("/api/logs/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    content = response.text
    assert "timestamp" in content
    assert "container_id" in content
