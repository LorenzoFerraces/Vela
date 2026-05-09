"""Fixtures for pytest API integration tests.

Orchestrator / image builder / traffic router are mocked so tests don't need
Docker. The database layer is replaced by an in-memory SQLite (aiosqlite).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.app import create_app
from app.api.deps import (
    get_db,
    get_image_builder,
    get_orchestrator,
    get_traffic_router,
)
from app.core.auth.passwords import hash_password
from app.core.auth.tokens import create_access_token
from app.core.default_image_builder import DefaultImageBuilder
from app.core.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
)
from app.core.enums import BuildStrategy, ContainerStatus, HealthStatus, SupportedLanguage
from app.core.models import BuildResult, ContainerInfo, ContainerStats, HealthResult, ProjectInfo
from app.core.orchestrator import ContainerOrchestrator
from app.core.traffic_router import NoopTrafficRouter
from app.db.base import Base
from app.db.models import User

os.environ.setdefault("VELA_AUTH_SECRET", "test-secret-please-do-not-use-in-prod")
os.environ.setdefault("VELA_AUTH_ACCESS_TOKEN_TTL_MINUTES", "60")


def make_container_info(*, owner_id: uuid.UUID | str, **overrides: object) -> ContainerInfo:
    labels: dict[str, str] = {
        VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
        VELA_OWNER_LABEL: str(owner_id),
    }
    extra_labels = overrides.pop("labels", None)
    if isinstance(extra_labels, dict):
        labels.update({str(k): str(v) for k, v in extra_labels.items()})
    data: dict[str, object] = {
        "id": "cid-1",
        "name": "vela-test",
        "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
        "ports": [],
        "labels": labels,
        "health": HealthStatus.NONE,
    }
    data.update(overrides)
    return ContainerInfo.model_validate(data)


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def sample_container(test_user_id: uuid.UUID) -> ContainerInfo:
    return make_container_info(owner_id=test_user_id)


@pytest.fixture
def mock_orchestrator(sample_container: ContainerInfo) -> MagicMock:
    orch = MagicMock(spec=ContainerOrchestrator)

    async def list_containers(
        *,
        status: ContainerStatus | None = None,
        owner_id: str | None = None,
    ) -> list[ContainerInfo]:
        rows = [sample_container]
        if owner_id is not None:
            rows = [
                row for row in rows if row.labels.get(VELA_OWNER_LABEL) == owner_id
            ]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows

    orch.deploy = AsyncMock(return_value=sample_container)
    orch.start = AsyncMock(return_value=sample_container)
    orch.stop = AsyncMock(return_value=sample_container)
    orch.restart = AsyncMock(return_value=sample_container)
    orch.remove = AsyncMock(return_value=None)
    orch.get = AsyncMock(return_value=sample_container)
    orch.list = AsyncMock(side_effect=list_containers)
    orch.logs = AsyncMock(return_value="log line\n")
    orch.pull_image = AsyncMock(return_value=None)
    orch.build_image = AsyncMock(return_value="sha256:deadbeef")
    orch.list_images = AsyncMock(return_value=["nginx:alpine"])
    orch.verify_image_reference_available = AsyncMock(return_value=None)

    orch.get_stats = AsyncMock(
        return_value=ContainerStats(
            container_id=sample_container.id,
            timestamp=datetime.now(timezone.utc),
            cpu_percent=1.0,
            memory_usage_bytes=1000,
            memory_limit_bytes=2000,
            memory_percent=50.0,
        )
    )
    orch.get_health = AsyncMock(
        return_value=HealthResult(
            status=HealthStatus.HEALTHY,
            timestamp=datetime.now(timezone.utc),
        )
    )

    async def _stream_logs_side_effect(
        *_args: object,
        **_kwargs: object,
    ):
        yield b"log line\n"

    orch.stream_logs = MagicMock(
        side_effect=lambda *a, **k: _stream_logs_side_effect()
    )

    return orch


@pytest.fixture
def noop_router() -> NoopTrafficRouter:
    return NoopTrafficRouter()


@pytest.fixture
def mock_image_builder(mock_orchestrator: MagicMock) -> MagicMock:
    builder = MagicMock(spec=DefaultImageBuilder)
    builder.build_from_source = AsyncMock(
        return_value=BuildResult(
            image_id="sha256:built",
            image_tag="vela/gitbuild:abc123",
            strategy=BuildStrategy.DOCKERFILE_EXISTS,
            build_log="",
            project_info=ProjectInfo(language=SupportedLanguage.PYTHON, has_dockerfile=True),
        )
    )
    builder.analyze = AsyncMock(
        return_value=ProjectInfo(language=SupportedLanguage.PYTHON, has_dockerfile=False)
    )
    return builder


@pytest.fixture
def db_session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    """In-memory SQLite session factory with the schema created up front."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(setup())

    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    email: str,
    password: str | None,
) -> User:
    async def run() -> User:
        async with factory() as session:
            user = User(
                id=user_id,
                email=email,
                password_hash=hash_password(password) if password else None,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return asyncio.run(run())


@pytest.fixture
def seeded_user(
    db_session_factory: async_sessionmaker[AsyncSession],
    test_user_id: uuid.UUID,
) -> User:
    return _seed_user(
        db_session_factory,
        user_id=test_user_id,
        email="user@example.com",
        password="correct-horse-battery-staple",
    )


@pytest.fixture
def seeded_other_user(
    db_session_factory: async_sessionmaker[AsyncSession],
    other_user_id: uuid.UUID,
) -> User:
    return _seed_user(
        db_session_factory,
        user_id=other_user_id,
        email="other@example.com",
        password="another-strong-password",
    )


def _build_app_with_overrides(
    *,
    db_session_factory: async_sessionmaker[AsyncSession],
    orchestrator: Any | None = None,
    image_builder: Any | None = None,
    traffic_router: Any | None = None,
) -> Any:
    app = create_app()

    async def _get_db_override() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    if orchestrator is not None:
        app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    if image_builder is not None:
        app.dependency_overrides[get_image_builder] = lambda: image_builder
    if traffic_router is not None:
        app.dependency_overrides[get_traffic_router] = lambda: traffic_router
    return app


@pytest.fixture
def unauth_app(
    db_session_factory: async_sessionmaker[AsyncSession],
    mock_orchestrator: MagicMock,
    mock_image_builder: MagicMock,
    noop_router: NoopTrafficRouter,
) -> Iterator[Any]:
    """App with all dependencies overridden but no Authorization header on the client."""
    app = _build_app_with_overrides(
        db_session_factory=db_session_factory,
        orchestrator=mock_orchestrator,
        image_builder=mock_image_builder,
        traffic_router=noop_router,
    )
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def api_client(
    unauth_app: Any,
    seeded_user: User,
) -> Iterator[TestClient]:
    """Authenticated test client (Authorization: Bearer <token>) for the seeded user."""
    token = create_access_token(seeded_user.id)
    with TestClient(unauth_app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def other_user_client(
    unauth_app: Any,
    seeded_other_user: User,
) -> Iterator[TestClient]:
    """Authenticated client for a *different* user — used to test ownership filtering."""
    token = create_access_token(seeded_other_user.id)
    with TestClient(unauth_app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def anonymous_client(unauth_app: Any) -> Iterator[TestClient]:
    """Unauthenticated client — every protected route should return 401."""
    with TestClient(unauth_app) as client:
        yield client


@pytest.fixture
def db_app(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Iterator[Any]:
    """Plain app with only the DB override (no mocks for orchestrator/builder)."""
    app = _build_app_with_overrides(db_session_factory=db_session_factory)
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(seeded_user: User) -> str:
    return create_access_token(seeded_user.id)


@pytest.fixture
def make_authed_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    seeded_user: User,
):
    """Return a builder for a TestClient with custom dependency overrides.

    Each call yields a ``(client, app)`` tuple via a context manager. The client
    is pre-authenticated as ``seeded_user``.
    """
    from contextlib import contextmanager

    token = create_access_token(seeded_user.id)

    @contextmanager
    def builder(
        *,
        orchestrator: Any | None = None,
        image_builder: Any | None = None,
        traffic_router: Any | None = None,
    ) -> Iterator[TestClient]:
        app = _build_app_with_overrides(
            db_session_factory=db_session_factory,
            orchestrator=orchestrator,
            image_builder=image_builder,
            traffic_router=traffic_router,
        )
        try:
            with TestClient(app) as client:
                client.headers["Authorization"] = f"Bearer {token}"
                yield client
        finally:
            app.dependency_overrides.clear()

    return builder
