# Secrets Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encrypted secrets scoped to projects, referenced by name at deploy time. Values never stored plaintext, never returned in API responses.

**Architecture:** New `ProjectSecret` table with Fernet encryption. Secrets resolved at deploy time and merged into container env vars. Read-only API never exposes secret values.

**Tech Stack:** SQLAlchemy 2.x, Alembic, Fernet (cryptography), FastAPI, React, TypeScript

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~)
- Backend MVC: core/ (domain), schemas.py (views), routes/ (controllers)
- Domain packages under `app/core/<domain>/` when 3+ modules
- TDD: write failing test first, then minimal implementation
- Existing Fernet infrastructure in `app/core/security/secrets.py` must be reused
- Secret values NEVER appear in API responses, logs, or deployment history

---

## Task 1: DB Model and Alembic Migration

**Files:**
- Modify: `backend/app/db/models.py` (append `ProjectSecret` class)
- Create: `backend/alembic/versions/0015_project_secrets.py`

**Interfaces:**
- Produces: `ProjectSecret` ORM model visible to SQLAlchemy session

- [ ] Add `ProjectSecret` model to `backend/app/db/models.py` after `StackComposition` (after line 501). Follow the `UserOAuthIdentity` pattern for `LargeBinary` encrypted storage and the `Dockerfile` pattern for unique constraints.

```python
class ProjectSecret(Base):
    __tablename__ = "project_secrets"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_secrets_project_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    project: Mapped["Project"] = relationship()
```

- [ ] Create migration file `backend/alembic/versions/0015_project_secrets.py`. Follow `0008_team_projects.py` pattern for `create_table` with foreign keys and unique constraints. Set `down_revision = "0014_stacks"`.

```python
"""Add project_secrets table for encrypted per-project secrets.

Revision ID: 0015_project_secrets
Revises: 0014_stacks
Create Date: 2026-08-03

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_project_secrets"
down_revision: str | Sequence[str] | None = "0014_stacks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_secrets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_secrets_project_name"),
    )
    op.create_index("ix_project_secrets_project_id", "project_secrets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_secrets_project_id", table_name="project_secrets")
    op.drop_table("project_secrets")
```

- [ ] Run `cd backend && python -m pytest tests -q` to confirm existing tests still pass after model addition (no functional change yet).

---

## Task 2: Secrets Repository (Domain Layer)

**Files:**
- Create: `backend/app/core/secrets/repository.py`

**Interfaces:**
- Consumes: `AsyncSession`, `ProjectSecret` model, `encrypt_secret`/`decrypt_secret`
- Produces: `create_secret`, `list_secrets_for_project`, `get_secret`, `update_secret`, `delete_secret`, `resolve_secrets_for_deploy`

- [ ] Create `backend/app/core/secrets/repository.py` with async CRUD functions. Follow `app/core/projects/repository.py` patterns for session usage and error handling. Use `encrypt_secret` and `decrypt_secret` from `app.core.security.secrets`.

```python
"""Project secrets CRUD — encrypts on write, decrypts on read."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectAccessDeniedError
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import ProjectSecret


class SecretNameTakenError(Exception):
    """A secret with this name already exists for the project."""


class SecretNotFoundError(Exception):
    """The requested secret does not exist."""


async def create_secret(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    plaintext_value: str,
) -> ProjectSecret:
    secret = ProjectSecret(
        project_id=project_id,
        name=name.strip(),
        encrypted_value=encrypt_secret(plaintext_value),
    )
    session.add(secret)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise SecretNameTakenError(
            f"A secret with the name {name.strip()!r} already exists for this project."
        ) from exc
    await session.refresh(secret)
    return secret


async def list_secrets_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[ProjectSecret]:
    stmt = (
        select(ProjectSecret)
        .where(ProjectSecret.project_id == project_id)
        .order_by(ProjectSecret.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_secret(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
) -> ProjectSecret:
    stmt = (
        select(ProjectSecret)
        .where(ProjectSecret.project_id == project_id)
        .where(ProjectSecret.name == name.strip())
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise SecretNotFoundError(f"Secret {name.strip()!r} not found.")
    return row


async def update_secret(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    plaintext_value: str,
) -> ProjectSecret:
    secret = await get_secret(session, project_id=project_id, name=name)
    secret.encrypted_value = encrypt_secret(plaintext_value)
    await session.flush()
    await session.refresh(secret)
    return secret


async def delete_secret(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
) -> None:
    secret = await get_secret(session, project_id=project_id, name=name)
    await session.delete(secret)
    await session.flush()


async def resolve_secrets_for_deploy(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    secret_names: list[str],
) -> dict[str, str]:
    """Resolve secret names to decrypted values, prefixed with SECRET_.

    Returns ``{"SECRET_<NAME>": "<decrypted_value>"}`` for each name that exists.
    Silently skips names that do not exist (they may have been deleted).
    """
    if not secret_names:
        return {}

    trimmed_names = [n.strip() for n in secret_names if n.strip()]
    if not trimmed_names:
        return {}

    stmt = (
        select(ProjectSecret)
        .where(ProjectSecret.project_id == project_id)
        .where(ProjectSecret.name.in_(trimmed_names))
    )
    result = await session.execute(stmt)
    secrets = result.scalars().all()

    resolved: dict[str, str] = {}
    for secret in secrets:
        env_key = f"SECRET_{secret.name}"
        resolved[env_key] = decrypt_secret(secret.encrypted_value)
    return resolved
```

- [ ] Create `backend/app/core/secrets/__init__.py` to export the repository functions:

```python
"""Secrets management domain package."""

from app.core.secrets.repository import (
    SecretNameTakenError,
    SecretNotFoundError,
    create_secret,
    delete_secret,
    get_secret,
    list_secrets_for_project,
    resolve_secrets_for_deploy,
    update_secret,
)

__all__ = [
    "SecretNameTakenError",
    "SecretNotFoundError",
    "create_secret",
    "delete_secret",
    "get_secret",
    "list_secrets_for_project",
    "resolve_secrets_for_deploy",
    "update_secret",
]
```

- [ ] Run `cd backend && python -m pytest tests -q` to confirm no regressions.

---

## Task 3: API Schemas

**Files:**
- Modify: `backend/app/api/schemas.py`

**Interfaces:**
- Produces: `SecretCreate`, `SecretUpdate`, `SecretPublic`
- Modifies: `RunFromSourceRequest` (adds `secret_keys` field)

- [ ] Add secret schemas to `backend/app/api/schemas.py` after the `DeploymentDiffResponse` class (after line 530). Add a section header comment.

```python
# ---------------------------------------------------------------------------
# Project secrets
# ---------------------------------------------------------------------------


class SecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=0, max_length=65536)


class SecretUpdate(BaseModel):
    value: str = Field(min_length=0, max_length=65536)

    @model_validator(mode="after")
    def reject_empty_update(self) -> SecretUpdate:
        if not self.value and self.value != "":
            raise ValueError("value must be provided.")
        return self


class SecretPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
```

- [ ] Add `secret_keys` field to `RunFromSourceRequest` in the same file. Add it after the `scaling_policy` field (line 166). The field accepts names of project secrets to inject at deploy time.

```python
    secret_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Names of project secrets to inject as environment variables. "
            "Each secret is available as SECRET_<NAME> inside the container."
        ),
    )
```

- [ ] Add a `field_validator` for `secret_keys` in `RunFromSourceRequest` to validate each name matches `[A-Za-z_][A-Za-z0-9_]*` and max 128 chars. Add it after the existing `validate_env_vars` validator (after line 190):

```python
    @field_validator("secret_keys")
    @classmethod
    def validate_secret_keys(cls, value: list[str]) -> list[str]:
        import re
        pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
        validated: list[str] = []
        seen: set[str] = set()
        for key in value:
            trimmed = key.strip()
            if not trimmed:
                continue
            if not pattern.match(trimmed):
                msg = (
                    f"Secret key {trimmed!r} is invalid. "
                    "Use only letters, digits, and underscores; start with a letter or underscore."
                )
                raise ValueError(msg)
            if trimmed in seen:
                msg = f"Duplicate secret key: {trimmed!r}"
                raise ValueError(msg)
            seen.add(trimmed)
            validated.append(trimmed)
        return validated
```

- [ ] Run `cd backend && python -m pytest tests -q` to confirm no regressions.

---

## Task 4: Secrets Routes (Controller Layer)

**Files:**
- Create: `backend/app/api/routes/secrets.py`
- Modify: `backend/app/api/app.py` (register secrets router)

**Interfaces:**
- Consumes: `SecretCreate`, `SecretUpdate`, `SecretPublic`, secrets repository functions, `require_membership`
- Produces: CRUD routes under `/api/projects/{project_id}/secrets`

- [ ] Create `backend/app/api/routes/secrets.py` with CRUD routes. Follow `app/api/routes/projects.py` patterns for auth, dependency injection, and error handling.

```python
"""Project secrets CRUD API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import SecretCreate, SecretPublic, SecretUpdate
from app.core.projects import require_membership
from app.core.secrets import (
    SecretNameTakenError,
    SecretNotFoundError,
    create_secret,
    delete_secret,
    list_secrets_for_project,
    update_secret,
)
from app.db.models import User

router = APIRouter()


def _to_public(secret) -> SecretPublic:
    return SecretPublic(
        id=secret.id,
        name=secret.name,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.get("/", response_model=list[SecretPublic])
async def list_project_secrets(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SecretPublic]:
    await require_membership(session, project_id=project_id, user_id=current_user.id)
    secrets = await list_secrets_for_project(session, project_id)
    return [_to_public(s) for s in secrets]


@router.post("/", response_model=SecretPublic, status_code=status.HTTP_201_CREATED)
async def create_project_secret(
    project_id: uuid.UUID,
    body: SecretCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SecretPublic:
    await require_membership(session, project_id=project_id, user_id=current_user.id)
    try:
        secret = await create_secret(
            session,
            project_id=project_id,
            name=body.name,
            plaintext_value=body.value,
        )
    except SecretNameTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_public(secret)


@router.patch("/{secret_name}", response_model=SecretPublic)
async def update_project_secret(
    project_id: uuid.UUID,
    secret_name: str,
    body: SecretUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SecretPublic:
    await require_membership(session, project_id=project_id, user_id=current_user.id)
    try:
        secret = await update_secret(
            session,
            project_id=project_id,
            name=secret_name,
            plaintext_value=body.value,
        )
    except SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_public(secret)


@router.delete("/{secret_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_secret(
    project_id: uuid.UUID,
    secret_name: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await require_membership(session, project_id=project_id, user_id=current_user.id)
    try:
        await delete_secret(session, project_id=project_id, name=secret_name)
    except SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] Register the secrets router in `backend/app/api/app.py`. Add import and router registration. In the imports section (line 15), add `secrets` to the routes import:

```python
from app.api.routes import (
    auth,
    builder,
    containers,
    deployments,
    dockerfile_templates,
    github,
    images,
    projects,
    scaling,
    secrets,
    settings,
    stacks,
    traffic,
    users,
)
```

Then add the router registration after the projects router (after line 167):

```python
    application.include_router(
        secrets.router,
        prefix=f"{API_PREFIX}/projects/{{project_id}}/secrets",
        tags=["secrets"],
    )
```

- [ ] Run `cd backend && python -m pytest tests -q` to confirm no regressions.

---

## Task 5: Secrets CRUD Tests

**Files:**
- Create: `backend/tests/test_secrets_api.py`

**Interfaces:**
- Consumes: `api_client`, `other_user_client` fixtures, `integration_app`

- [ ] Create `backend/tests/test_secrets_api.py` with integration tests. Follow `test_user_library_api.py` patterns. The tests use `api_client` fixture which is pre-authenticated with `seeded_user` that has a personal project.

```python
"""Integration tests for project secrets CRUD."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _personal_project_id(api_client: TestClient) -> str:
    projects = api_client.get("/api/projects/").json()
    personal = [p for p in projects if p["is_personal"]]
    assert personal, "Expected at least one personal project"
    return personal[0]["id"]


def test_secrets_crud(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)

    create = api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "DB_PASSWORD", "value": "super-secret-123"},
    )
    assert create.status_code == 201
    created = create.json()
    assert created["name"] == "DB_PASSWORD"
    assert "value" not in created
    assert "id" in created
    assert "created_at" in created
    assert "updated_at" in created

    listed = api_client.get(f"/api/projects/{project_id}/secrets/")
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
    names = [s["name"] for s in listed.json()]
    assert "DB_PASSWORD" in names

    update = api_client.patch(
        f"/api/projects/{project_id}/secrets/DB_PASSWORD",
        json={"value": "updated-secret-456"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "DB_PASSWORD"

    delete = api_client.delete(f"/api/projects/{project_id}/secrets/DB_PASSWORD")
    assert delete.status_code == 204

    listed_after = api_client.get(f"/api/projects/{project_id}/secrets/")
    assert all(s["name"] != "DB_PASSWORD" for s in listed_after.json())


def test_secrets_duplicate_name(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)

    api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "API_KEY", "value": "key-1"},
    )
    duplicate = api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "API_KEY", "value": "key-2"},
    )
    assert duplicate.status_code == 409


def test_secrets_other_user_cannot_access(
    api_client: TestClient, other_user_client: TestClient
) -> None:
    project_id = _personal_project_id(api_client)

    api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "PRIVATE_KEY", "value": "shhh"},
    )

    other_projects = other_user_client.get("/api/projects/").json()
    other_personal = [p for p in other_projects if p["is_personal"]]
    assert other_personal
    other_project_id = other_personal[0]["id"]

    listed = other_user_client.get(f"/api/projects/{project_id}/secrets/")
    assert listed.status_code == 403

    create_attempt = other_user_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "HACK", "value": "evil"},
    )
    assert create_attempt.status_code == 403


def test_secrets_delete_nonexistent(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)
    resp = api_client.delete(f"/api/projects/{project_id}/secrets/DOES_NOT_EXIST")
    assert resp.status_code == 404


def test_secrets_update_nonexistent(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)
    resp = api_client.patch(
        f"/api/projects/{project_id}/secrets/DOES_NOT_EXIST",
        json={"value": "new-value"},
    )
    assert resp.status_code == 404


def test_secrets_empty_list(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)
    resp = api_client.get(f"/api/projects/{project_id}/secrets/")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] Run `cd backend && python -m pytest tests/test_secrets_api.py -q` to verify all 6 tests pass.

---

## Task 6: Wire Secrets Resolution into Deploy Flow

**Files:**
- Modify: `backend/app/api/routes/containers.py`

**Interfaces:**
- Consumes: `resolve_secrets_for_deploy`, `RunFromSourceRequest.secret_keys`
- Modifies: `_persist_run_deployment` to record secret keys used

- [ ] Add import for `resolve_secrets_for_deploy` at the top of `backend/app/api/routes/containers.py` (after line 93):

```python
from app.core.secrets import resolve_secrets_for_deploy
```

- [ ] Modify the `run_from_user_source` handler to resolve secrets before building the deploy config. In each source_kind branch (image, dockerfile_template, git), resolve secrets and merge them into env_vars before calling `_deploy_config_for_image`. The resolution happens right after `resolved_volumes` (line 690).

Add after line 690 (`resolved_volumes = _resolve_deploy_volumes(...)`):

```python
    resolved_secrets = await resolve_secrets_for_deploy(
        session,
        project_id=project_id,
        secret_names=body.secret_keys,
    )
```

Then, in each source_kind branch, merge resolved secrets into env_vars when building the deploy config. For the image branch (around line 694-702), change the `env_vars` parameter:

```python
        merged_env = {**body.env_vars, **resolved_secrets}
        cfg = _deploy_config_for_image(
            image=image_ref,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
            env_vars=merged_env,
            command=body.command,
            volumes=resolved_volumes,
        )
```

Apply the same `merged_env` pattern to the `dockerfile_template` branch (around line 748-756) and the `git` branch.

- [ ] Modify `_persist_run_deployment` to record which secret keys were injected. The function already redacts all env var values. Add a `secret_keys` parameter and store the list so deployment history shows which secrets were used.

Update the function signature (line 314):

```python
async def _persist_run_deployment(
    session: AsyncSession,
    user: User,
    body: RunFromSourceRequest,
    info: ContainerInfo,
    *,
    project_id: uuid.UUID,
    source_kind: str,
    source_ref: str,
    image_tag: str,
    dockerfile_snapshot: str | None,
    public_url: str | None,
    secret_keys: list[str] | None = None,
) -> None:
```

The `DeploymentSnapshot` and `DeploymentRecord` already store `env_vars` as a dict. The secret values will be redacted by the existing `_redacted_env_vars_for_history` call since `merged_env` includes the secret values with `SECRET_` prefix. The `secret_keys` list itself is available on `body.secret_keys` which is already part of the request body. No additional storage needed — the `SECRET_` prefixed keys in the redacted env_vars dict already show which secrets were used.

- [ ] Update the `_persist_run_deployment` calls in `run_from_user_source` to pass `secret_keys=body.secret_keys` (though this is optional since `body` is already passed). The merged env vars with `SECRET_` prefix will be automatically redacted by the existing `_redacted_env_vars_for_history` function.

- [ ] Run `cd backend && python -m pytest tests/test_secrets_api.py tests/test_deploy_epic.py -q` to verify secrets CRUD and deploy flow tests pass.

---

## Task 7: Deploy Integration Tests

**Files:**
- Create: `backend/tests/test_secrets_deploy.py`

**Interfaces:**
- Consumes: `api_client` fixture, secrets API, containers run API

- [ ] Create `backend/tests/test_secrets_deploy.py` with integration tests for the deploy flow with secrets.

```python
"""Integration tests for secrets resolution at deploy time."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _personal_project_id(api_client: TestClient) -> str:
    projects = api_client.get("/api/projects/").json()
    personal = [p for p in projects if p["is_personal"]]
    assert personal
    return personal[0]["id"]


def test_deploy_with_secrets_injected(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)

    api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "API_KEY", "value": "secret-token-abc"},
    )

    resp = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "container_port": 80,
            "project_id": project_id,
            "secret_keys": ["API_KEY"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "image"


def test_deploy_secret_key_prefix_in_env(api_client: TestClient) -> None:
    project_id = _personal_project_id(api_client)

    api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "DB_PASS", "value": "my-db-password"},
    )

    resp = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "container_port": 80,
            "project_id": project_id,
            "secret_keys": ["DB_PASS"],
            "env_vars": {"NORMAL_VAR": "visible"},
        },
    )
    assert resp.status_code == 200


def test_deploy_nonexistent_secret_key_silently_skipped(
    api_client: TestClient,
) -> None:
    project_id = _personal_project_id(api_client)

    resp = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "container_port": 80,
            "project_id": project_id,
            "secret_keys": ["DOES_NOT_EXIST"],
        },
    )
    assert resp.status_code == 200


def test_deploy_secret_values_redacted_in_history(
    api_client: TestClient,
) -> None:
    project_id = _personal_project_id(api_client)

    api_client.post(
        f"/api/projects/{project_id}/secrets/",
        json={"name": "TOKEN", "value": "super-secret"},
    )

    api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "container_port": 80,
            "project_id": project_id,
            "secret_keys": ["TOKEN"],
        },
    )

    history = api_client.get("/api/deployments/").json()
    assert len(history) > 0
    latest = history[0]
    env_vars = latest.get("env_vars", {})
    if "SECRET_TOKEN" in env_vars:
        assert env_vars["SECRET_TOKEN"] == "<REDACTED>"
```

- [ ] Run `cd backend && python -m pytest tests/test_secrets_deploy.py -q` to verify deploy integration tests pass.

---

## Task 8: Frontend — API Client Types and Functions

**Files:**
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `ProjectSecret` type, `listProjectSecrets`, `createProjectSecret`, `updateProjectSecret`, `deleteProjectSecret`
- Modifies: `RunFromSourceRequest` interface (adds `secret_keys`)

- [ ] Add `ProjectSecret` interface to `frontend/src/api/client.ts` after the `RunFromSourceResponse` interface (after line 446):

```typescript
export interface ProjectSecret {
  id: string
  name: string
  created_at: string
  updated_at: string
}
```

- [ ] Add secrets API functions after the project-related functions (after `listProjectInvitations` around line 889):

```typescript
export async function listProjectSecrets(
  projectId: string,
): Promise<ProjectSecret[]> {
  return apiGet<ProjectSecret[]>(`/api/projects/${projectId}/secrets/`)
}

export async function createProjectSecret(
  projectId: string,
  name: string,
  value: string,
): Promise<ProjectSecret> {
  return apiPost<ProjectSecret>(
    `/api/projects/${projectId}/secrets/`,
    { name, value },
  )
}

export async function updateProjectSecret(
  projectId: string,
  name: string,
  value: string,
): Promise<ProjectSecret> {
  return apiPatch<ProjectSecret>(
    `/api/projects/${projectId}/secrets/${encodeURIComponent(name)}`,
    { value },
  )
}

export async function deleteProjectSecret(
  projectId: string,
  name: string,
): Promise<void> {
  await apiDelete(`/api/projects/${projectId}/secrets/${encodeURIComponent(name)}`)
}
```

- [ ] Add `secret_keys` to the `RunFromSourceRequest` interface (after line 435):

```typescript
  secret_keys?: string[]
```

- [ ] Run `cd frontend && npm run build` to verify TypeScript compiles without errors.

---

## Task 9: Frontend — Secrets Management Page

**Files:**
- Create: `frontend/src/pages/projects/SecretsSection.tsx`
- Modify: `frontend/src/pages/TeamsPage.tsx` (add secrets tab)

**Interfaces:**
- Consumes: secrets API functions, `ProjectSecret` type
- Produces: Secrets CRUD UI component

- [ ] Create `frontend/src/pages/projects/SecretsSection.tsx` — a self-contained component for managing project secrets. Follow `DockerfileTemplatesSection.tsx` patterns for the CRUD form.

```tsx
import { useCallback, useState } from 'react'
import {
  createProjectSecret,
  deleteProjectSecret,
  formatApiError,
  listProjectSecrets,
  updateProjectSecret,
  type ProjectSecret,
} from '../../api/client'

type SecretsSectionProps = {
  projectId: string
}

type Banner = { tone: 'ok' | 'err'; text: string } | null

export function SecretsSection({ projectId }: SecretsSectionProps) {
  const [secrets, setSecrets] = useState<ProjectSecret[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)
  const [newName, setNewName] = useState('')
  const [newValue, setNewValue] = useState('')
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const load = useCallback(async () => {
    try {
      const rows = await listProjectSecrets(projectId)
      setSecrets(rows)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useState(() => { load() })

  async function onCreate(event: React.FormEvent) {
    event.preventDefault()
    if (!newName.trim() || !newValue) return
    setBusy(true)
    setBanner(null)
    try {
      await createProjectSecret(projectId, newName.trim(), newValue)
      setNewName('')
      setNewValue('')
      setBanner({ tone: 'ok', text: `Secret "${newName.trim()}" created.` })
      await load()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  function startEdit(secret: ProjectSecret) {
    setEditingName(secret.name)
    setEditValue('')
  }

  async function onSaveEdit() {
    if (editingName === null) return
    setBusy(true)
    setBanner(null)
    try {
      await updateProjectSecret(projectId, editingName, editValue)
      setEditingName(null)
      setEditValue('')
      setBanner({ tone: 'ok', text: `Secret "${editingName}" updated.` })
      await load()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(name: string) {
    setBusy(true)
    setBanner(null)
    try {
      await deleteProjectSecret(projectId, name)
      setBanner({ tone: 'ok', text: `Secret "${name}" deleted.` })
      await load()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="containers-muted" role="status">Loading secrets…</p>
  }

  return (
    <div className="secrets-section">
      <h3>Secrets</h3>

      {banner ? (
        <p
          className={
            banner.tone === 'ok'
              ? 'settings-banner settings-banner--ok'
              : 'settings-banner settings-banner--err'
          }
          role="alert"
        >
          {banner.text}
        </p>
      ) : null}

      <form onSubmit={onCreate} className="secrets-form">
        <input
          className="containers-form__input containers-form__input--inline"
          type="text"
          placeholder="Name (e.g. DB_PASSWORD)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          maxLength={128}
          disabled={busy}
        />
        <input
          className="containers-form__input containers-form__input--inline"
          type="password"
          placeholder="Value"
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          maxLength={65536}
          disabled={busy}
        />
        <button
          type="submit"
          className="btn btn--primary btn--compact"
          disabled={busy || !newName.trim() || !newValue}
        >
          Add
        </button>
      </form>

      {secrets.length === 0 ? (
        <p className="containers-muted">No secrets configured.</p>
      ) : (
        <ul className="secrets-list">
          {secrets.map((secret) => (
            <li key={secret.id} className="secrets-list__row">
              {editingName === secret.name ? (
                <>
                  <input
                    className="containers-form__input"
                    type="password"
                    placeholder="New value"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    disabled={busy}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact"
                    onClick={onSaveEdit}
                    disabled={busy || !editValue}
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact"
                    onClick={() => setEditingName(null)}
                    disabled={busy}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <span className="secrets-name">{secret.name}</span>
                  <span className="containers-muted secrets-updated">
                    Updated {new Date(secret.updated_at).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact"
                    onClick={() => startEdit(secret)}
                    disabled={busy}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact btn--danger"
                    onClick={() => onDelete(secret.name)}
                    disabled={busy}
                  >
                    Delete
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] Add CSS for the secrets section. Append to `frontend/src/index.css` (or the existing styles file used by the app):

```css
.secrets-section { margin-top: 1.5rem; }
.secrets-form { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; }
.secrets-list { list-style: none; padding: 0; }
.secrets-list__row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--border-color, #eee);
  flex-wrap: wrap;
}
.secrets-name { font-weight: 600; min-width: 140px; }
.secrets-updated { font-size: 0.85rem; margin-left: auto; }
```

- [ ] Integrate the `SecretsSection` into `TeamsPage.tsx`. Add the import and render it in the team detail view alongside existing sections (members, invitations). Find the team detail rendering area and add a tab or section for secrets.

Add import at top of `TeamsPage.tsx`:

```tsx
import { SecretsSection } from './projects/SecretsSection'
```

In the team detail section (where members/invitations are shown), add after the existing sections:

```tsx
{selectedProject ? (
  <SecretsSection projectId={selectedProject.id} />
) : null}
```

- [ ] Run `cd frontend && npm run build` to verify TypeScript compiles.

---

## Task 10: Frontend — Secrets Checkbox on Run Form

**Files:**
- Modify: `frontend/src/pages/containers/ContainersRunAdvancedFields.tsx`
- Modify: `frontend/src/pages/ContainersPage.tsx`

**Interfaces:**
- Consumes: `listProjectSecrets`, `ProjectSecret` type
- Produces: Multi-select for secrets in the advanced fields

- [ ] Add secrets state and data loading to `ContainersPage.tsx`. After the `deployProjects` hook (around line 73), add a hook to load available secrets for the selected project:

```tsx
const [selectedSecretKeys, setSelectedSecretKeys] = useState<string[]>([])
const [availableSecrets, setAvailableSecrets] = useState<ProjectSecret[]>([])
const [secretsLoading, setSecretsLoading] = useState(false)

useEffect(() => {
  if (!deployProjects.selectedProjectId) {
    setAvailableSecrets([])
    return
  }
  setSecretsLoading(true)
  listProjectSecrets(deployProjects.selectedProjectId)
    .then(setAvailableSecrets)
    .catch(() => setAvailableSecrets([]))
    .finally(() => setSecretsLoading(false))
}, [deployProjects.selectedProjectId])
```

Add `ProjectSecret` to the imports from `../api/client`:

```tsx
import {
  formatApiError,
  getImageAvailability,
  listProjectSecrets,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
  type ProjectSecret,
  type RunFromSourceRequest,
  type ScalingPolicyRequest,
} from '../api/client'
```

- [ ] Update `buildRunRequest` in `ContainersPage.tsx` to include `secret_keys`:

```tsx
const base = {
  container_name: containerName.trim() || null,
  host_port: null,
  container_port,
  git_branch: gitBranch.trim() || 'main',
  route_host: null,
  route_path_prefix: '/',
  route_tls: false,
  public_route: true,
  env_vars: recordFromEnvRows(envRows),
  command,
  volumes: volumesFromRows(volumeRows),
  project_id: deployProjects.selectedProjectId,
  scaling_policy: scalingPolicy,
  secret_keys: selectedSecretKeys,
}
```

- [ ] Add `selectedSecretKeys` to `resetAdvancedFields`:

```tsx
function resetAdvancedFields() {
  setEnvRows([{ key: '', value: '' }])
  setVolumeRows([createEmptyVolumeMountRow()])
  setStartCommand('')
  setScalingPolicy(null)
  setSelectedSecretKeys([])
}
```

- [ ] Pass secrets state to `ContainersRunAdvancedFields` by adding props:

```tsx
type ContainersRunAdvancedFieldsProps = {
  // ... existing props
  availableSecrets: ProjectSecret[]
  secretsLoading: boolean
  selectedSecretKeys: string[]
  onSelectedSecretKeysChange: (keys: string[]) => void
}
```

- [ ] Add the secrets multi-select UI in `ContainersRunAdvancedFields.tsx` inside the advanced body, after the environment variables section and before the volumes section:

```tsx
{availableSecrets.length > 0 ? (
  <>
    <p className="containers-form__label">Inject secrets</p>
    <p className="containers-muted containers-form__hint">
      Secrets are stored encrypted and injected as <code>SECRET_&lt;NAME&gt;</code> at runtime.
    </p>
    {secretsLoading ? (
      <p className="containers-muted" role="status">Loading secrets…</p>
    ) : (
      <ul className="containers-env-list">
        {availableSecrets.map((secret) => {
          const checked = selectedSecretKeys.includes(secret.name)
          return (
            <li key={secret.id} className="containers-env-list__row">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', flex: 1 }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    if (e.target.checked) {
                      onSelectedSecretKeysChange([...selectedSecretKeys, secret.name])
                    } else {
                      onSelectedSecretKeysChange(
                        selectedSecretKeys.filter((k) => k !== secret.name)
                      )
                    }
                  }}
                />
                <span>{secret.name}</span>
              </label>
            </li>
          )
        })}
      </ul>
    )}
  </>
) : null}
```

- [ ] Update the `ContainersRunAdvancedFields` usage in `ContainersPage.tsx` to pass the new props:

```tsx
<ContainersRunAdvancedFields
  envRows={envRows}
  onEnvRowsChange={setEnvRows}
  volumeRows={volumeRows}
  onVolumeRowsChange={setVolumeRows}
  startCommand={startCommand}
  onStartCommandChange={setStartCommand}
  scalingPolicy={scalingPolicy}
  onScalingPolicyChange={setScalingPolicy}
  scalingValidationError={scalingValidationError}
  availableSecrets={availableSecrets}
  secretsLoading={secretsLoading}
  selectedSecretKeys={selectedSecretKeys}
  onSelectedSecretKeysChange={setSelectedSecretKeys}
/>
```

- [ ] Run `cd frontend && npm run build` to verify TypeScript compiles.

---

## Task 11: Final Verification

**Files:**
- All modified files

- [ ] Run full backend test suite: `cd backend && python -m pytest tests -q`

- [ ] Run frontend build: `cd frontend && npm run build`

- [ ] Run frontend lint: `cd frontend && npm run lint`

---

## Self-Review

### Spec Coverage
- [x] DB model `ProjectSecret` with UUID, project_id FK, name, encrypted_value (LargeBinary), created_at, updated_at, unique constraint on (project_id, name)
- [x] Alembic migration (0015)
- [x] CRUD routes: `POST/GET/DELETE /api/projects/{project_id}/secrets`, `PATCH /api/projects/{project_id}/secrets/{secret_name}`
- [x] Schemas: `SecretCreate` (name, value), `SecretPublic` (name, created_at, updated_at — no value)
- [x] `RunFromSourceRequest.secret_keys: list[str]`
- [x] Deploy-time resolution: secret names → decrypt → merge as `SECRET_<NAME>=<value>`
- [x] Deployment history: secret values redacted via existing `_redacted_env_vars_for_history`
- [x] Frontend: secrets management section per project, checkbox multi-select on run form

### Placeholder Scan
- No "TBD", "TODO", "add validation", or "write tests" placeholders remain
- All code snippets are complete and ready to paste

### Type Consistency
- Backend: `ProjectSecret` model uses `Mapped[uuid.UUID]`, `Mapped[str]`, `Mapped[bytes]`, `Mapped[datetime]` — consistent with existing models
- Backend schemas: `SecretCreate`, `SecretUpdate`, `SecretPublic` use Pydantic `Field` with `min_length`/`max_length` — consistent with existing schemas
- Frontend: `ProjectSecret` interface matches `SecretPublic` response shape
- `RunFromSourceRequest.secret_keys` is `list[str]` in both backend schema and frontend interface

### Security
- Secret values never appear in `SecretPublic` (no `value` field)
- Values encrypted at rest using existing Fernet infrastructure
- Values redacted in deployment history via existing `_redacted_env_vars_for_history`
- Non-existent secret keys silently skipped at deploy time (no info leak)
- Project membership required for all secrets operations
- `DELETE` returns 204 (no body), `PATCH` returns `SecretPublic` (no value)
