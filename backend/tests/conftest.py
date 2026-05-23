"""Fixtures for pytest API integration tests.

Uses in-memory SQLite and :class:`~app.core.fake_orchestrator.FakeContainerOrchestrator`
so tests exercise real route and builder wiring without Docker.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

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
from app.core.enums import ContainerStatus, HealthStatus
from app.core.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo
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
def fake_orchestrator(sample_container: ContainerInfo) -> FakeContainerOrchestrator:
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(sample_container)
    orchestrator.register_image("nginx:alpine")
    return orchestrator


@pytest.fixture
def image_builder(fake_orchestrator: FakeContainerOrchestrator) -> DefaultImageBuilder:
    return DefaultImageBuilder(orchestrator=fake_orchestrator)


@pytest.fixture
def noop_router() -> NoopTrafficRouter:
    return NoopTrafficRouter()


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
def db_app(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Iterator[Any]:
    """App with only the DB override (real orchestrator/builder from env)."""
    app = _build_app_with_overrides(db_session_factory=db_session_factory)
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def integration_app(
    db_session_factory: async_sessionmaker[AsyncSession],
    fake_orchestrator: FakeContainerOrchestrator,
    image_builder: DefaultImageBuilder,
    noop_router: NoopTrafficRouter,
) -> Iterator[Any]:
    """App with SQLite DB, fake orchestrator, and real image builder."""
    app = _build_app_with_overrides(
        db_session_factory=db_session_factory,
        orchestrator=fake_orchestrator,
        image_builder=image_builder,
        traffic_router=noop_router,
    )
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def api_client(
    integration_app: Any,
    seeded_user: User,
) -> Iterator[TestClient]:
    """Authenticated test client (Authorization: Bearer <token>) for the seeded user."""
    token = create_access_token(seeded_user.id)
    with TestClient(integration_app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def other_user_client(
    integration_app: Any,
    seeded_other_user: User,
) -> Iterator[TestClient]:
    """Authenticated client for a *different* user — used to test ownership filtering."""
    token = create_access_token(seeded_other_user.id)
    with TestClient(integration_app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def anonymous_client(integration_app: Any) -> Iterator[TestClient]:
    """Unauthenticated client — every protected route should return 401."""
    with TestClient(integration_app) as client:
        yield client


@pytest.fixture
def auth_token(seeded_user: User) -> str:
    return create_access_token(seeded_user.id)


@pytest.fixture
def make_authed_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    seeded_user: User,
    fake_orchestrator: FakeContainerOrchestrator,
    image_builder: DefaultImageBuilder,
    noop_router: NoopTrafficRouter,
):
    """Return a builder for a TestClient with optional dependency overrides."""
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
            orchestrator=orchestrator if orchestrator is not None else fake_orchestrator,
            image_builder=image_builder if image_builder is not None else DefaultImageBuilder(
                orchestrator=orchestrator if orchestrator is not None else fake_orchestrator
            ),
            traffic_router=traffic_router if traffic_router is not None else noop_router,
        )
        try:
            with TestClient(app) as client:
                client.headers["Authorization"] = f"Bearer {token}"
                yield client
        finally:
            app.dependency_overrides.clear()

    return builder
