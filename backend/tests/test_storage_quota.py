"""Tests for team (project) storage quota."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
    _inspect_to_container_info,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import TeamStorageQuotaExceededError
from app.core.models import ContainerInfo
from app.core.quotas import storage_quota
from app.db.base import Base
from app.db.models import (
    AlertHistory,
    EmailPreference,
    Organization,
    Project,
    ProjectMembership,
    User,
)


@pytest_asyncio.fixture
async def quota_db() -> AsyncSession:
    """In-memory SQLite session with the full ORM schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_storage_quota_column(quota_db: AsyncSession) -> None:
    organization = Organization(name="quota org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Team A",
        is_personal=False,
        storage_quota_bytes=1024,
    )
    quota_db.add(project)
    await quota_db.commit()
    loaded = (await quota_db.execute(select(Project))).scalar_one()
    assert loaded.storage_quota_bytes == 1024


@pytest.mark.asyncio
async def test_alert_history_container_id_nullable(quota_db: AsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="quota@example.com")
    quota_db.add(user)
    await quota_db.flush()
    history = AlertHistory(
        user_id=user.id,
        container_id=None,
        event_type="storage",
        alert_hash="0" * 64,
        sent_at=datetime.now(timezone.utc),
        status="sent",
    )
    quota_db.add(history)
    await quota_db.commit()
    loaded = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalar_one()
    assert loaded.container_id is None


_INSPECT_BASE = {
    "Id": "abc123",
    "Name": "/vela-app",
    "State": {"Status": "running"},
    "Config": {"Image": "nginx:alpine", "Labels": {}},
    "Created": "2026-04-01T12:00:00Z",
}


def test_inspect_mapping_reads_size_rw() -> None:
    info = _inspect_to_container_info({**_INSPECT_BASE, "SizeRw": 4096})
    assert info.disk_bytes == 4096


def test_inspect_mapping_defaults_disk_bytes_to_zero() -> None:
    info = _inspect_to_container_info(_INSPECT_BASE)
    assert info.disk_bytes == 0


_GB = 1024 ** 3


def _make_info(
    project_id: uuid.UUID | None, disk_bytes: int, owner_id: uuid.UUID
) -> ContainerInfo:
    """Build a fake container record; project-unlabeled when project_id is None."""
    labels = {
        VELA_MANAGED_LABEL: "true",
        VELA_OWNER_LABEL: str(owner_id),
    }
    if project_id is not None:
        labels[VELA_PROJECT_LABEL] = str(project_id)
    return ContainerInfo.model_validate(
        {
            "id": f"cid-{uuid.uuid4().hex[:8]}",
            "name": "vela-quota-test",
            "image": "nginx:alpine",
            "status": ContainerStatus.RUNNING,
            "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ports": [],
            "labels": labels,
            "health": HealthStatus.NONE,
            "disk_bytes": disk_bytes,
        }
    )


@pytest.fixture(autouse=True)
def _reset_over_quota_state() -> None:
    storage_quota.reset_over_quota_state()


def test_environment_quota_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert storage_quota.environment_quota_bytes() is None
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "not-a-number")
    assert storage_quota.environment_quota_bytes() is None
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    assert storage_quota.environment_quota_bytes() == _GB


def test_effective_quota_resolution_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert (
        storage_quota.effective_quota_bytes(Project(storage_quota_bytes=None))
        is None
    )
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=5)) == 5
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "10")
    assert (
        storage_quota.effective_quota_bytes(Project(storage_quota_bytes=None))
        == 10
    )
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=5)) == 5
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=15)) == 10


def test_quota_source_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert storage_quota.quota_source(Project(storage_quota_bytes=None)) == "unlimited"
    assert storage_quota.quota_source(Project(storage_quota_bytes=1)) == "team"
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    assert storage_quota.quota_source(Project(storage_quota_bytes=None)) == "platform"


@pytest.mark.asyncio
async def test_team_storage_usage_counts_project_containers_and_member_uploads(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization(name="usage org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(organization_id=organization.id, name="Team A")
    other = Project(organization_id=organization.id, name="Team B")
    quota_db.add_all([project, other])
    await quota_db.flush()
    member = User(id=uuid.uuid4(), email="member@example.com")
    quota_db.add(member)
    await quota_db.flush()
    quota_db.add(
        ProjectMembership(project_id=project.id, user_id=member.id, role="owner")
    )
    await quota_db.commit()

    uploads: dict[uuid.UUID, int] = {member.id: 50}
    monkeypatch.setattr(
        storage_quota,
        "user_uploads_total_bytes",
        lambda user_id: uploads.get(user_id, 0),
    )

    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_make_info(project.id, 100, uuid.uuid4()))
    orchestrator.seed_container(_make_info(project.id, 300, uuid.uuid4()))
    orchestrator.seed_container(_make_info(other.id, 999, uuid.uuid4()))
    # Legacy container without a project label, owned by a user whose
    # personal project IS `project` — must count for `project`.
    legacy_owner = User(id=uuid.uuid4(), email="legacy@example.com")
    legacy_owner.personal_project_id = project.id
    quota_db.add(legacy_owner)
    await quota_db.commit()
    orchestrator.seed_container(_make_info(None, 25, legacy_owner.id))

    disk, uploads_bytes = await storage_quota.team_storage_usage(
        quota_db, orchestrator, project.id
    )
    assert disk == 425
    assert uploads_bytes == 50

    disk_other, _ = await storage_quota.team_storage_usage(
        quota_db, orchestrator, other.id
    )
    assert disk_other == 999


@pytest.mark.asyncio
async def test_enforce_team_storage_capacity(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization(name="enforce org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Full team",
        storage_quota_bytes=400,
    )
    quota_db.add(project)
    await quota_db.commit()
    monkeypatch.setattr(storage_quota, "user_uploads_total_bytes", lambda user_id: 0)

    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_make_info(project.id, 400, uuid.uuid4()))

    with pytest.raises(TeamStorageQuotaExceededError) as excinfo:
        await storage_quota.enforce_team_storage_capacity(
            quota_db, orchestrator, project.id
        )
    assert "Full team" in str(excinfo.value)
    assert "storage quota" in str(excinfo.value)

    # Unlimited team: no error with the same usage.
    unlimited = Project(organization_id=organization.id, name="Free team")
    quota_db.add(unlimited)
    await quota_db.flush()
    orchestrator.seed_container(_make_info(unlimited.id, 10_000, uuid.uuid4()))
    await storage_quota.enforce_team_storage_capacity(
        quota_db, orchestrator, unlimited.id
    )


def test_run_blocked_when_team_quota_exceeded(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "1024")
    # cid-1 carries the seeded user's owner label and no project label, so it
    # counts for their personal project.
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    assert seeded_user.personal_project_id is not None
    response = api_client.post(
        "/api/containers/run",
        json={"source_kind": "image", "image_ref": "nginx:alpine"},
    )
    assert response.status_code == 400
    assert "storage quota" in response.json()["detail"]


def test_run_allowed_under_team_quota(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * _GB))
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    response = api_client.post(
        "/api/containers/run",
        json={"source_kind": "image", "image_ref": "nginx:alpine"},
    )
    assert response.status_code == 200


def test_deploy_blocked_when_team_quota_exceeded(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "1024")
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    response = api_client.post(
        "/api/containers/deploy",
        json={
            "image": "nginx:alpine",
            "project_id": str(seeded_user.personal_project_id),
        },
    )
    assert response.status_code == 400
    assert "storage quota" in response.json()["detail"]


def test_upload_blocked_when_team_storage_quota_exceeded(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VELA_VOLUME_UPLOAD_USER_QUOTA_BYTES", str(150 * 1024**2))
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(1024 * 1024))

    first = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder/a.bin", b"x" * (1024 * 1024)))],
    )
    assert first.status_code == 200, first.text

    second = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder/b.bin", b"x" * (1024 * 1024 + 8)))],
    )
    assert second.status_code == 400
    assert "storage quota" in second.json()["detail"]


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-min-8-chars"},
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def _personal_project_id(client: TestClient) -> str:
    return next(
        project["id"]
        for project in client.get("/api/projects/").json()
        if project["is_personal"]
    )


def test_storage_quota_get_for_member(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the upload-scan directory so local dev uploads can't skew the total.
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(1024 * 1024))
    fake_orchestrator.set_disk_bytes("cid-1", 10 * 1024)
    project_id = seeded_user.personal_project_id
    assert project_id is not None

    response = api_client.get(f"/api/projects/{project_id}/storage-quota")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quota_bytes"] == 1024 * 1024
    assert body["container_disk_bytes"] == 10 * 1024
    assert body["uploads_bytes"] == 0
    assert body["used_bytes"] == 10 * 1024
    assert body["over_quota"] is False
    assert body["source"] == "platform"


def test_storage_quota_requires_membership(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    with TestClient(db_app) as owner_client, TestClient(db_app) as stranger_client:
        _register(owner_client, "quota-owner@example.com")
        owner_project_id = _personal_project_id(owner_client)

        _register(stranger_client, "quota-stranger@example.com")
        response = stranger_client.get(
            f"/api/projects/{owner_project_id}/storage-quota"
        )
        assert response.status_code == 403


def test_patch_storage_quota_rejects_above_platform_limit(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * 1024 * 1024))
    with TestClient(db_app) as client:
        _register(client, "quota-patch@example.com")
        project_id = _personal_project_id(client)
        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": 20 * 1024 * 1024},
        )
        assert response.status_code == 400
        assert "platform limit" in response.json()["detail"]


def test_patch_storage_quota_owner_sets_and_clears(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * _GB))
    with TestClient(db_app) as client:
        _register(client, "quota-set@example.com")
        project_id = _personal_project_id(client)

        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": 5 * _GB},
        )
        assert response.status_code == 200, response.text
        assert response.json()["quota_bytes"] == 5 * _GB
        assert response.json()["source"] == "team"

        listed = client.get("/api/projects/").json()
        assert next(
            project for project in listed if project["id"] == project_id
        )["storage_quota_bytes"] == 5 * _GB

        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": None},
        )
        assert response.status_code == 200
        assert response.json()["quota_bytes"] == 10 * _GB
        assert response.json()["source"] == "platform"


def test_patch_storage_quota_forbidden_for_non_owner(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as member_client:
        _register(owner_client, "quota-team-owner@example.com")
        create_response = owner_client.post(
            "/api/projects/", json={"name": "Quota team"}
        )
        assert create_response.status_code == 201, create_response.text
        team_id = create_response.json()["id"]

        _register(member_client, "quota-team-member@example.com")
        invitation = owner_client.post(
            f"/api/projects/{team_id}/invitations",
            json={"email": "quota-team-member@example.com", "role": "viewer"},
        )
        assert invitation.status_code == 201, invitation.text
        incoming = member_client.get("/api/projects/invitations/incoming").json()
        accept = member_client.post(
            f"/api/projects/invitations/{incoming[0]['id']}/accept"
        )
        assert accept.status_code == 200, accept.text

        response = member_client.patch(
            f"/api/projects/{team_id}/storage-quota",
            json={"storage_quota_bytes": _GB},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_check_team_storage_quotas_alerts_rising_edge_once(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.notifications.alert_service import AlertService
    from app.core.notifications.email_provider import ConsoleProvider

    organization = Organization(name="alert org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Alert team",
        storage_quota_bytes=400,
    )
    quota_db.add(project)
    await quota_db.flush()
    member = User(id=uuid.uuid4(), email="alert-member@example.com")
    quota_db.add(member)
    await quota_db.flush()
    quota_db.add(
        ProjectMembership(project_id=project.id, user_id=member.id, role="owner")
    )
    await quota_db.commit()
    monkeypatch.setattr(storage_quota, "user_uploads_total_bytes", lambda user_id: 0)

    orchestrator = FakeContainerOrchestrator()
    container = _make_info(project.id, 100, member.id)
    orchestrator.seed_container(container)
    orchestrator.set_disk_bytes(container.id, 500)

    # Patch AlertService so the test asserts on dispatch decisions, not email I/O.
    dispatched: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def fake_send(
        self: AlertService,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        project_name: str,
        used_bytes: int,
        quota_bytes: int,
    ) -> bool:
        dispatched.append((user_id, project_id))
        return True

    monkeypatch.setattr(
        AlertService, "send_project_storage_alert", fake_send, raising=True
    )

    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert storage_quota.currently_over_quota_projects() == frozenset(
        {project.id}
    )
    assert dispatched == [(member.id, project.id)]

    # Second pass while still over: no duplicate dispatch.
    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert dispatched == [(member.id, project.id)]

    # Back under the limit clears the over-quota state.
    orchestrator.set_disk_bytes(container.id, 100)
    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert project.id not in storage_quota.currently_over_quota_projects()


@pytest.mark.asyncio
async def test_project_storage_alert_sent_and_deduplicated(
    quota_db: AsyncSession,
) -> None:
    from app.core.notifications.email_provider import ConsoleProvider

    from app.core.notifications.alert_service import AlertService

    user = User(id=uuid.uuid4(), email="storage-alert@example.com")
    quota_db.add(user)
    await quota_db.flush()
    quota_db.add(
        EmailPreference(
            user_id=user.id,
            email="storage-alert@example.com",
            alerts_enabled=True,
            alert_types=[],
            alert_frequency="immediate",
        )
    )
    await quota_db.commit()

    service = AlertService(ConsoleProvider(), quota_db)
    project_id = uuid.uuid4()
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=project_id,
            project_name="Alert team",
            used_bytes=500,
            quota_bytes=400,
        )
        is True
    )
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=project_id,
            project_name="Alert team",
            used_bytes=500,
            quota_bytes=400,
        )
        is False
    )
    rows = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].container_id is None
    assert rows[0].email_sent_to == "storage-alert@example.com"


@pytest.mark.asyncio
async def test_project_storage_alert_respects_disabled_notifications(
    quota_db: AsyncSession,
) -> None:
    from app.core.notifications.alert_service import AlertService
    from app.core.notifications.email_provider import ConsoleProvider

    user = User(id=uuid.uuid4(), email="quiet@example.com")
    quota_db.add(user)
    await quota_db.flush()
    quota_db.add(
        EmailPreference(
            user_id=user.id,
            email="quiet@example.com",
            alerts_enabled=False,
            alert_types=["stop"],
            alert_frequency="immediate",
        )
    )
    await quota_db.commit()

    service = AlertService(ConsoleProvider(), quota_db)
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=uuid.uuid4(),
            project_name="Quiet team",
            used_bytes=500,
            quota_bytes=400,
        )
        is False
    )
    rows = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalars().all()
    assert rows == []
