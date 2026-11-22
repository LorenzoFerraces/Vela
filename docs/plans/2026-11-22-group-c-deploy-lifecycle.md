# Group C — Deploy lifecycle & secrets (F14, F13, F15, F10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add write-only versioned secrets with `secret://` references, config update with a dry-run diff, GitHub App push-to-deploy webhooks, and TTL-bound PR preview environments.

**Architecture:** One `0026_*` migration adds all new tables. `F14` resolves `secret://name@version` into a **runtime-only** `DeployConfig` copy right before `orchestrator.deploy`; the persisted encrypted snapshot and the history `env_vars` column keep the references, never plaintext. `F13` loads that snapshot, classifies fields into mutable vs identity/topology, rejects recreation-triggering changes, and calls the existing `_deploy_and_maybe_wire_route` + history/audit path so a normal history entry is written. `F15` adds a GitHub App credential service (PyJWT is already a dependency) and an unauthenticated webhook receiver mounted **outside `/api`**, with HMAC + 5-minute skew + unique-delivery-id dedup. `F10` reuses the webhook and the existing source-deploy worker with preview labels, a preview hostname prefix, clamped limits, TTL and a GC loop.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Fernet (`encrypt_secret`/`decrypt_secret`), PyJWT (already pinned), stdlib `hmac`/`hashlib`, pytest, React/TypeScript, Playwright.

## Global Constraints

- Worktree root: `C:\Users\lolo\.local\share\opencode\worktree\ab1b01\defect-remediation`. Paths are relative to it.
- Implementation order within this plan: Task 1 → 2 → 3 → 4 → 5 → 6. F10 depends on F14 and F15.
- Alembic: Group B claims `0025_externalized_state`; this plan uses **`0026_group_c_lifecycle`** with `down_revision = "0025_externalized_state"` (confirm the parent at merge time; never create a second head).
- Secret plaintext must never reach `DeploymentRecord.env_vars`, `DeploymentRecordPublic`, `DeploymentDiffResponse`, an audit log, or any API response. The only place it may exist is the runtime `DeployConfig` passed to `orchestrator.deploy`.
- Webhook receiver must be mounted outside `/api` so `test_route_auth_regression.py` keeps passing unchanged; if mounted under `/api`, its path must be added to `PUBLIC_PATHS` in that test.
- Preview deploys must reject `secret://` references and production env keys before the worker starts, especially for fork PRs.
- Verification per task: `cd backend && python -m pytest tests -q` (env `VELA_FAKE_ORCHESTRATOR=1`, `VELA_DATABASE_URL=sqlite+aiosqlite:///:memory:`) and `ruff check . && mypy app/ tests/`; frontend tasks additionally `cd frontend && npm run typecheck && npm run lint && npm run build`, plus the relevant Playwright spec.

---

### Task 1: F14 — secret models, migration, write-only store

**Files:**
- Modify: `backend/app/db/models.py`, `backend/app/core/exceptions.py`, `backend/app/api/errors.py`
- Create: `backend/alembic/versions/0026_group_c_lifecycle.py`, `backend/app/core/secret_store.py`
- Test: `backend/tests/test_secret_store.py`

**Interfaces:**
- Consumes: `encrypt_secret`, `decrypt_secret`, `require_membership`, `ProjectRole`.
- Produces: `create_secret(session, *, owner_user_id, project_id, name, value) -> SecretPublic`, `set_secret_value`, `get_secret_version`, `resolve_secret_reference(session, *, scope, name, version) -> str`, `SecretPublic`.

- [ ] **Step 1: Add exception classes** to `backend/app/core/exceptions.py`

```python
class SecretNotFoundError(VelaError):
    """A named secret does not exist in the requested scope."""


class SecretVersionNotFoundError(VelaError):
    """The requested immutable secret version does not exist."""


class DeploymentConfigChangeRequiresRecreateError(VelaError):
    """A config update changes an identity/topology field and needs recreation."""


class GitHubAppNotConfiguredError(VelaError):
    """No GitHub App credentials are configured."""


class WebhookSignatureError(VelaError):
    """Webhook HMAC signature is invalid."""


class WebhookReplayError(VelaError):
    """Webhook timestamp is outside the skew window or delivery id was seen before."""


class PreviewSecretForbiddenError(VelaError):
    """A preview deploy attempted to use a production secret or env value."""
```

Register `SecretNotFoundError`, `SecretVersionNotFoundError` and `PreviewSecretForbiddenError` as 404/400 handlers in `backend/app/api/errors.py` following the `TeamStorageQuotaError` handler at lines 243-251; register `WebhookSignatureError` and `WebhookReplayError` as 400 handlers.

- [ ] **Step 2: Add all Group C models** to `backend/app/db/models.py`

```python
class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SecretVersion(Base):
    __tablename__ = "secret_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    secret_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("secrets.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GitHubAppInstall(Base):
    __tablename__ = "github_app_installs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    private_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    webhook_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GitHubAppInstallationId(Base):
    __tablename__ = "github_app_installation_ids"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_install_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("github_app_installs.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GitHubWebhookConfig(Base):
    __tablename__ = "github_webhook_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    branch_filters: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preview_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preview_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GitHubWebhookDelivery(Base):
    __tablename__ = "github_webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    repo_full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_fork: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    sender_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PreviewDeploy(Base):
    __tablename__ = "preview_deploys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route_host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Create `backend/alembic/versions/0026_group_c_lifecycle.py`**

```python
"""group c lifecycle

Revision ID: 0026_group_c_lifecycle
Revises: 0025_externalized_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_group_c_lifecycle"
down_revision = "0025_externalized_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "secret_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("secret_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["secret_id"], ["secrets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_id", "version"),
    )
    op.create_table(
        "github_app_installs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(128), nullable=True),
        sa.Column("private_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "github_app_installation_ids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("app_install_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.String(64), nullable=False),
        sa.Column("account_login", sa.String(128), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["app_install_id"], ["github_app_installs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_install_id", "project_id"),
    )
    op.create_table(
        "github_webhook_configs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("branch_filters", sa.JSON(), nullable=False),
        sa.Column("preview_enabled", sa.Boolean(), nullable=False),
        sa.Column("preview_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "github_webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("branch", sa.String(256), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("is_fork", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
    )
    op.create_index("ix_github_webhook_deliveries_received_at", "github_webhook_deliveries", ["received_at"])
    op.create_table(
        "preview_deploys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=True),
        sa.Column("container_name", sa.String(128), nullable=True),
        sa.Column("route_host", sa.String(253), nullable=True),
        sa.Column("public_url", sa.String(512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "repo_full_name", "pr_number"),
    )
    op.create_index("ix_preview_deploys_expires_at", "preview_deploys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_preview_deploys_expires_at", table_name="preview_deploys")
    op.drop_table("preview_deploys")
    op.drop_index("ix_github_webhook_deliveries_received_at", table_name="github_webhook_deliveries")
    op.drop_table("github_webhook_deliveries")
    op.drop_table("github_webhook_configs")
    op.drop_table("github_app_installation_ids")
    op.drop_table("github_app_installs")
    op.drop_table("secret_versions")
    op.drop_table("secrets")
```

- [ ] **Step 4: Implement `backend/app/core/secret_store.py`**

```python
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SecretNotFoundError, SecretVersionNotFoundError
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import Secret, SecretVersion

SECRET_REF_PATTERN = re.compile(r"^secret://([A-Za-z0-9_.-]+)(?:@(\d+|latest))?$")


def parse_secret_reference(value: str) -> tuple[str, str] | None:
    match = SECRET_REF_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1), match.group(2) or "latest"


async def create_secret(
    session: AsyncSession, *, owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None, name: str, value: str,
) -> Secret:
    secret = Secret(owner_user_id=owner_user_id, project_id=project_id, name=name)
    session.add(secret)
    await session.flush()
    session.add(SecretVersion(secret_id=secret.id, version=1, value_encrypted=encrypt_secret(value)))
    await session.commit()
    return secret


async def set_secret_value(session: AsyncSession, secret: Secret, value: str) -> SecretVersion:
    latest = (await session.execute(
        select(func.max(SecretVersion.version)).where(SecretVersion.secret_id == secret.id)
    )).scalar() or 0
    version = SecretVersion(
        secret_id=secret.id, version=latest + 1, value_encrypted=encrypt_secret(value),
    )
    session.add(version)
    secret.updated_at = datetime.now(UTC)
    await session.commit()
    return version


async def resolve_secret_reference(
    session: AsyncSession, *, owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None, name: str, version: str,
) -> str:
    query = select(Secret).where(Secret.name == name)
    query = query.where(Secret.project_id == project_id) if project_id is not None else query.where(Secret.owner_user_id == owner_user_id)
    secret = (await session.execute(query)).scalar_one_or_none()
    if secret is None:
        raise SecretNotFoundError(f"Secret {name!r} was not found")
    if version == "latest":
        row = (await session.execute(
            select(SecretVersion).where(SecretVersion.secret_id == secret.id).order_by(SecretVersion.version.desc()).limit(1)
        )).scalar_one_or_none()
    else:
        row = (await session.execute(
            select(SecretVersion).where(SecretVersion.secret_id == secret.id, SecretVersion.version == int(version))
        )).scalar_one_or_none()
    if row is None:
        raise SecretVersionNotFoundError(f"Secret {name!r} has no version {version}")
    return decrypt_secret(row.value_encrypted)
```

- [ ] **Step 5: Write failing tests** in `backend/tests/test_secret_store.py`

```python
import uuid
import pytest
from app.core.exceptions import SecretNotFoundError, SecretVersionNotFoundError
from app.core.secret_store import create_secret, parse_secret_reference, resolve_secret_reference, set_secret_value
from app.db.models import Secret


@pytest.mark.asyncio
async def test_write_only_versions_and_resolution(db_session_factory) -> None:
    user_id = uuid.uuid4()
    async with db_session_factory() as session:
        secret = await create_secret(session, owner_user_id=user_id, project_id=None, name="DB_URL", value="postgres://one")
        first = await set_secret_value(session, secret, "postgres://two")
        assert first.version == 2
        assert await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="DB_URL", version="1") == "postgres://one"
        assert await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="DB_URL", version="latest") == "postgres://two"


@pytest.mark.asyncio
async def test_missing_secret_and_version_are_actionable(db_session_factory) -> None:
    user_id = uuid.uuid4()
    async with db_session_factory() as session:
        with pytest.raises(SecretNotFoundError):
            await resolve_secret_reference(session, owner_user_id=user_id, project_id=None, name="MISSING", version="latest")


def test_reference_pattern() -> None:
    assert parse_secret_reference("secret://DB_URL@2") == ("DB_URL", "2")
    assert parse_secret_reference("plain-value") is None
```

- [ ] **Step 6: Verify and commit**

Run: `cd backend && python -m pytest tests/test_secret_store.py -q && alembic upgrade head && ruff check .`

```bash
git add backend/app/db/models.py backend/alembic/versions/0026_group_c_lifecycle.py backend/app/core/secret_store.py backend/app/core/exceptions.py backend/app/api/errors.py backend/tests/test_secret_store.py
git commit -m "feat(secrets): add write-only versioned secret store"
```

---

### Task 2: F14 — resolve references into a runtime-only deploy config

**Files:**
- Create: `backend/app/core/deploy/secret_resolution.py`
- Modify: `backend/app/api/routes/containers.py`, `backend/app/api/schemas.py`, `backend/app/api/routes/secrets.py` (new)
- Test: `backend/tests/test_secret_resolution.py`, update `backend/tests/test_deploy_epic.py`

**Interfaces:**
- Consumes: `resolve_secret_reference`, `DeployConfig`.
- Produces: `async def runtime_config_with_secrets(session, config: DeployConfig, *, owner_user_id, project_id, allow_secrets: bool = True) -> DeployConfig`; `GET/POST/PATCH/DELETE /api/secrets`.

- [ ] **Step 1: Write a failing test** in `backend/tests/test_secret_resolution.py`

```python
import uuid
from app.core.deploy.secret_resolution import runtime_config_with_secrets
from app.core.models import DeployConfig
from app.core.secret_store import create_secret


def test_runtime_copy_is_resolved_but_original_keeps_reference(db_session_factory) -> None:
    user_id = uuid.uuid4()
    config = DeployConfig(image="nginx", name="web", env_vars={"DB": "secret://DB_URL@latest"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            await create_secret(session, owner_user_id=user_id, project_id=None, name="DB_URL", value="postgres://real")
            runtime = await runtime_config_with_secrets(session, config, owner_user_id=user_id, project_id=None)
            assert runtime.env_vars["DB"] == "postgres://real"
            assert config.env_vars["DB"] == "secret://DB_URL@latest"
    import asyncio
    asyncio.run(scenario())


def test_previews_reject_secret_references(db_session_factory) -> None:
    from app.core.exceptions import PreviewSecretForbiddenError
    import asyncio
    config = DeployConfig(image="nginx", env_vars={"DB": "secret://DB_URL"})
    async def scenario() -> None:
        async with db_session_factory() as session:
            try:
                await runtime_config_with_secrets(session, config, owner_user_id=uuid.uuid4(), project_id=None, allow_secrets=False)
            except PreviewSecretForbiddenError:
                return
            raise AssertionError("expected PreviewSecretForbiddenError")
    asyncio.run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_secret_resolution.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `backend/app/core/deploy/secret_resolution.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PreviewSecretForbiddenError
from app.core.models import DeployConfig
from app.core.secret_store import parse_secret_reference, resolve_secret_reference


async def runtime_config_with_secrets(
    session: AsyncSession, config: DeployConfig, *, owner_user_id: uuid.UUID,
    project_id: uuid.UUID | None, allow_secrets: bool = True,
) -> DeployConfig:
    resolved: dict[str, str] = {}
    for key, value in config.env_vars.items():
        reference = parse_secret_reference(value)
        if reference is None:
            resolved[key] = value
            continue
        if not allow_secrets:
            raise PreviewSecretForbiddenError(f"Secret reference in env key {key!r} is not allowed for previews")
        name, version = reference
        resolved[key] = await resolve_secret_reference(
            session, owner_user_id=owner_user_id, project_id=project_id, name=name, version=version,
        )
    return config.model_copy(update={"env_vars": resolved})
```

- [ ] **Step 4: Wire into the three deploy paths** in `backend/app/api/routes/containers.py`

In each path (synchronous image deploy, dockerfile_template worker, git worker), create the runtime copy immediately before the `orchestrator.deploy(...)` call, and keep all `model_dump(mode="json")` history persistence calls operating on the **original** config:

```python
    runtime_config = await runtime_config_with_secrets(
        session, config, owner_user_id=user_id, project_id=project_id,
    )
    info, wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, runtime_config,
    )
```

Change the redaction helper `_redacted_env_vars_for_history` so a value matching `secret://...` is kept verbatim instead of replaced by `<REDACTED>`; all other values still become `<REDACTED>`.

- [ ] **Step 5: Add the secrets API** in `backend/app/api/routes/secrets.py` and mount it in `app.py` at `/api/secrets`

Schemas in `backend/app/api/schemas.py`:

```python
class SecretPublic(BaseModel):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    has_value: bool
    latest_version: int
    created_at: datetime


class SecretCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., min_length=1)
    project_id: uuid.UUID | None = None


class SecretValueUpdate(BaseModel):
    value: str = Field(..., min_length=1)
```

Routes: `GET /` (list secrets visible to user via `list_project_ids_for_user`), `POST /` (create with `require_membership` + `can_write` when project-scoped, else personal), `PATCH /{id}` (rotation = new version), `DELETE /{id}`. **No route returns a plaintext value** — `SecretPublic.has_value` is always `true` and `latest_version` is the only version metadata. Register the router in `backend/app/api/app.py` with `get_current_user` at router level.

- [ ] **Step 6: Update `backend/tests/test_deploy_epic.py`** so the expected history env value for a `secret://` reference is the reference itself, while ordinary env values remain `<REDACTED>`; add one assertion that `fake_orchestrator.last_deploy_config.env_vars` contains the resolved plaintext (proving the runtime copy was used).

- [ ] **Step 7: Verify and commit**

Run: `cd backend && python -m pytest tests/test_secret_resolution.py tests/test_deploy_epic.py -q && ruff check .`

```bash
git add backend/app/core/deploy/secret_resolution.py backend/app/api/routes/containers.py backend/app/api/routes/secrets.py backend/app/api/schemas.py backend/app/api/app.py backend/tests/test_secret_resolution.py backend/tests/test_deploy_epic.py
git commit -m "feat(secrets): resolve secret refs without leaking them into history"
```

---

### Task 3: F13 — dry-run diff and config update endpoint

**Files:**
- Modify: `backend/app/api/schemas.py`, `backend/app/core/deploy/deployment_history.py`, `backend/app/api/routes/deployments.py`, `frontend/src/api/builds.ts`, `frontend/src/pages/containers/DeploymentHistorySection.tsx`, `frontend/src/api/client.ts`
- Test: `backend/tests/test_deployment_update.py`, `frontend/e2e/dashboard.spec.ts`

**Interfaces:**
- Consumes: `load_deploy_config_snapshot`, `_deploy_and_maybe_wire_route`, `runtime_config_with_secrets`.
- Produces: `POST /api/deployments/{id}/dry-run`, `PATCH /api/deployments/{id}`, `DeploymentUpdateDryRunResponse`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_deployment_update.py`

```python
from app.core.exceptions import DeploymentConfigChangeRequiresRecreateError


def test_dry_run_returns_non_secret_config_diff(api_client) -> None:
    # create a deploy via the existing helper, then:
    response = api_client.post(f"/api/deployments/{deployment_id}/dry-run", json={"env_vars": {"B": "2"}, "command": ["node", "app.js"]})
    assert response.status_code == 200
    body = response.json()
    assert body["env"]["added"]["B"] == "2"
    assert body["config"]["command"] == ["node", "app.js"]
    assert "secret" not in str(body["config"])


def test_identity_change_requires_recreate(api_client) -> None:
    response = api_client.patch(f"/api/deployments/{deployment_id}", json={"image": "other-image"})
    assert response.status_code == 400


def test_patch_writes_a_new_history_entry(api_client, db_session_factory) -> None:
    response = api_client.patch(f"/api/deployments/{deployment_id}", json={"env_vars": {"B": "2"}})
    assert response.status_code == 200
    # assert a second DeploymentRecord row exists with env_vars {"B": "<REDACTED>"}
```

Create the seed deploy with the `wait_for_deploy`/`_create_job` pattern from `backend/tests/test_deploy_epic.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_deployment_update.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Add schemas** in `backend/app/api/schemas.py`

```python
class DeploymentUpdateRequest(BaseModel):
    env_vars: dict[str, str] | None = None
    command: list[str] | None = None
    labels: dict[str, str] | None = None
    health_check: HealthCheckConfig | None = None
    cpu_limit: float | None = None
    memory_limit: int | None = None
    route_host: str | None = None
    route_path_prefix: str | None = None
    route_tls: bool | None = None
    public_route: bool | None = None


class ConfigFieldDiff(BaseModel):
    before: object | None = None
    after: object | None = None


class DeploymentUpdateDryRunResponse(DeploymentDiffResponse):
    config: dict[str, ConfigFieldDiff]
```

- [ ] **Step 4: Add the field classifier and diff** to `backend/app/core/deploy/deployment_history.py`

```python
MUTABLE_FIELDS = frozenset({
    "env_vars", "command", "labels", "health_check", "cpu_limit", "memory_limit",
    "route_host", "route_path_prefix", "route_tls", "public_route", "restart_policy",
})


def classify_update(update: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    mutable = {key: value for key, value in update.items() if key in MUTABLE_FIELDS}
    rejected = sorted(
        key for key, value in update.items()
        if key not in MUTABLE_FIELDS and key in DeployConfig.model_fields and value is not None
    )
    return mutable, rejected


def diff_config_fields(before: DeployConfig, after: DeployConfig) -> dict[str, ConfigFieldDiff]:
    return {
        field: ConfigFieldDiff(before=getattr(before, field), after=getattr(after, field))
        for field in sorted(MUTABLE_FIELDS)
        if getattr(before, field) != getattr(after, field)
    }
```

Import `ConfigFieldDiff` from `app.api.schemas` — if that creates a core→api dependency, define the small `ConfigFieldDiff` shape in `core/deploy/deployment_history.py` and have the schema re-export it instead.

- [ ] **Step 5: Add the routes** to `backend/app/api/routes/deployments.py`

Both handlers load the deployment row (`get_deployment` scoping), load the snapshot via `load_deploy_config_snapshot(session, row.container_id)`, call `classify_update(body.model_dump(exclude_none=True))`, and raise `DeploymentConfigChangeRequiresRecreateError` naming the rejected fields. The dry-run builds the candidate with `candidate = snapshot.model_copy(update=mutable)` and returns `DeploymentUpdateDryRunResponse` with the existing `diff_deployments` fields plus `diff_config_fields(snapshot, candidate)`. The PATCH uses the same candidate through `runtime_config_with_secrets` → `_deploy_and_maybe_wire_route` → `_persist_run_deployment` → `emit_audit_log`, then returns the new `DeploymentRecordPublic`. Reject label edits to `VELA_OWNER_LABEL`/`VELA_PROJECT_LABEL` with a clear error — those keys are re-applied by `_apply_deploy_labels`.

- [ ] **Step 6: Frontend** — extend `frontend/src/api/builds.ts` with `DeploymentUpdateRequest`, `ConfigFieldDiff`, `DeploymentUpdateDryRunResponse`, `dryRunDeployment(id, body)` and `updateDeployment(id, body)`; re-export from `client.ts`. In `DeploymentHistorySection.tsx`, reuse the existing two-select compare panel to show the `config` diff (non-secret fields only, with a short label per field), and add a "Review & apply" flow: dry-run on click → review panel → confirm button calls update → refresh history. Use existing `role="alert"` / `role="status"` / skeleton patterns and `deployment-history__*` classes.

- [ ] **Step 7: Verify and commit**

Run:
```bash
cd backend && python -m pytest tests/test_deployment_update.py tests/test_deploy_epic.py -q && ruff check .
cd ../frontend && npm run typecheck && npm run lint && npm run build && npm run test:e2e -- e2e/dashboard.spec.ts
```

```bash
git add backend/app/api/schemas.py backend/app/core/deploy/deployment_history.py backend/app/api/routes/deployments.py frontend/src/api/builds.ts frontend/src/api/client.ts frontend/src/pages/containers/DeploymentHistorySection.tsx backend/tests/test_deployment_update.py frontend/e2e/dashboard.spec.ts
git commit -m "feat(deploy): add config dry-run and patch update"
```

---

### Task 4: F15 — GitHub App installation tokens and webhook receiver

**Files:**
- Create: `backend/app/core/github_app.py`, `backend/app/api/routes/webhooks.py`
- Modify: `backend/app/api/app.py`, `backend/app/api/schemas.py`, `backend/app/api/deps.py`, `backend/app/api/errors.py`
- Test: `backend/tests/test_github_app.py`, `backend/tests/test_webhooks.py`

**Interfaces:**
- Consumes: `GitHubAppInstall`, `GitHubWebhookConfig`, `GitHubWebhookDelivery`, `encrypt_secret`/`decrypt_secret`, `spawn_deploy_worker`.
- Produces: `installation_token(session, project_id) -> str`, `verify_github_signature(payload, secret, signature) -> bool`, `POST /webhooks/github/{project_id}`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_webhooks.py`

```python
import hashlib
import hmac
import json
from datetime import UTC, datetime
import pytest


def _headers(payload: dict, secret: str, delivery_id: str, timestamp: datetime) -> dict[str, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
        "content-type": "application/json",
    }


def test_webhook_rejects_bad_signature(api_client) -> None:
    response = api_client.post("/webhooks/github/00000000-0000-0000-0000-000000000001", content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Delivery": "d1", "X-GitHub-Event": "push"})
    assert response.status_code == 400


def test_webhook_dedups_delivery_ids(api_client, db_session_factory) -> None:
    import asyncio
    import uuid
    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall, GitHubWebhookConfig

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(GitHubAppInstall(
                app_id="123", private_key_encrypted=encrypt_secret("pem"),
                webhook_secret_encrypted=encrypt_secret("hook-secret"),
            ))
            session.add(GitHubWebhookConfig(
                project_id=project_id, repo_full_name="org/repo", enabled=True,
                branch_filters=[], preview_enabled=False, preview_ttl_seconds=3600,
            ))
            await session.commit()

    asyncio.run(seed())
    payload = {"repository": {"full_name": "org/repo"}, "ref": "refs/heads/main"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _headers(payload, "hook-secret", "d-up-1", datetime.now(UTC))
    url = f"/webhooks/github/{project_id}"
    first = api_client.post(url, content=body, headers=headers)
    second = api_client.post(url, content=body, headers=headers)
    assert first.json()["status"] == "received"
    assert second.json()["status"] == "duplicate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_webhooks.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement `backend/app/core/github_app.py`**

```python
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GitHubAppNotConfiguredError, WebhookReplayError, WebhookSignatureError
from app.core.security.secrets import decrypt_secret
from app.db.models import GitHubAppInstall, GitHubAppInstallationId
import httpx


def verify_github_signature(payload: bytes, secret: str, signature: str | None) -> bool:
    if signature is None or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def check_timestamp(timestamp: datetime | None, now: datetime | None = None) -> None:
    moment = now or datetime.now(UTC)
    if timestamp is None or abs((moment - timestamp).total_seconds()) > 300:
        raise WebhookReplayError("Webhook timestamp is outside the 5-minute window")


async def installation_token(session: AsyncSession, project_id: uuid.UUID) -> str:
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    if install is None:
        raise GitHubAppNotConfiguredError("GitHub App is not configured")
    mapping = (await session.execute(
        select(GitHubAppInstallationId).where(GitHubAppInstallationId.project_id == project_id)
    )).scalar_one_or_none()
    if mapping is None:
        raise GitHubAppNotConfiguredError("No GitHub App installation is linked to this project")
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": install.app_id},
        decrypt_secret(install.private_key_encrypted), algorithm="RS256",
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{mapping.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return str(response.json()["token"])
```

- [ ] **Step 4: Implement the webhook receiver** in `backend/app/api/routes/webhooks.py`

```python
router = APIRouter()

@router.post("/webhooks/github/{project_id}")
async def github_webhook(
    project_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db),
    registry: DeployJobRegistry = Depends(get_deploy_jobs),
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    payload = await request.body()
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    signature = request.headers.get("X-Hub-Signature-256")
    event = request.headers.get("X-GitHub-Event", "")
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    if install is None:
        raise GitHubAppNotConfiguredError("GitHub App is not configured")
    if not verify_github_signature(payload, decrypt_secret(install.webhook_secret_encrypted), signature):
        raise WebhookSignatureError("Invalid webhook signature")

    existing = (await session.execute(
        select(GitHubWebhookDelivery).where(GitHubWebhookDelivery.delivery_id == delivery_id)
    )).scalar_one_or_none()
    if existing is not None:
        return {"status": "duplicate"}

    body = json.loads(payload)
    config = (await session.execute(
        select(GitHubWebhookConfig).where(
            GitHubWebhookConfig.project_id == project_id,
            GitHubWebhookConfig.repo_full_name == body["repository"]["full_name"],
            GitHubWebhookConfig.enabled.is_(True),
        )
    )).scalar_one_or_none()
    if config is None:
        return {"status": "ignored"}

    branch = body.get("ref", "").removeprefix("refs/heads/")
    if config.branch_filters and branch not in config.branch_filters:
        return {"status": "ignored"}

    timestamp = datetime.fromisoformat(body.get("timestamp", "").replace("Z", "+00:00")) if body.get("timestamp") else None
    check_timestamp(timestamp)

    delivery = GitHubWebhookDelivery(
        delivery_id=delivery_id, project_id=project_id,
        repo_full_name=body["repository"]["full_name"], event=event,
        action=body.get("action"), branch=branch,
        sender_timestamp=timestamp, status="received",
    )
    session.add(delivery)
    await session.commit()
    return {"status": "received"}
```

Add PR metadata (`pr_number`, `is_fork`) for `pull_request` events and call the shared deploy enqueue helper from Task 6.

- [ ] **Step 5: Mount the router outside `/api`** in `backend/app/api/app.py`

```python
application.include_router(webhooks.router, tags=["webhooks"])
```

No `/api` prefix. Add a test asserting `GET /api/...` auth regression still passes:

Run: `cd backend && python -m pytest tests/test_route_auth_regression.py tests/test_webhooks.py -q`
Expected: PASS (the new path is outside the `/api` scan).

- [ ] **Step 6: GitHub App config API** — add `PUT /api/settings/github-app` (admin only, `require_admin`) storing App id/slug/PEM/webhook secret via `encrypt_secret`; `GET` returns metadata only (`has_key`-style booleans); `PUT /api/projects/{id}/github-webhook` and `GET /api/projects/{id}/github-webhook` for project-scoped repo/filters/preview settings, gated by `require_owner` or `require_admin`; `GET /api/projects/{id}/github-webhook/deliveries` for delivery history. Add matching schemas with no plaintext fields.

- [ ] **Step 7: Private-repo token path** — add to `backend/app/core/deploy/github_auth.py`:

```python
async def github_token_for_project(session: AsyncSession, project_id: uuid.UUID, user) -> str | None:
    try:
        return await installation_token(session, project_id)
    except GitHubAppNotConfiguredError:
        return github_token_for_url(session, user, "https://github.com/")
```

Use it at `containers.py:1054` in place of the PAT-only call so App tokens are preferred and the existing PAT remains a fallback.

- [ ] **Step 8: Verify and commit**

Run: `cd backend && python -m pytest tests/test_github_app.py tests/test_webhooks.py tests/test_github_oauth.py tests/test_route_auth_regression.py -q && ruff check .`

```bash
git add backend/app/core/github_app.py backend/app/api/routes/webhooks.py backend/app/api/app.py backend/app/api/schemas.py backend/app/api/errors.py backend/app/core/deploy/github_auth.py backend/app/db/models.py backend/alembic/versions/0026_group_c_lifecycle.py backend/tests/test_github_app.py backend/tests/test_webhooks.py
git commit -m "feat(webhooks): add GitHub App installation and signed webhook receiver"
```

---

### Task 5: F15 frontend — App config and delivery history

**Files:**
- Create: `frontend/src/api/githubApp.ts`, `frontend/src/pages/settings/GitHubAppCard.tsx`, `frontend/src/pages/teams/WebhookSettings.tsx`, `frontend/src/pages/teams/webhook-settings.css`
- Modify: `frontend/src/api/client.ts`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/teams/TeamDetail.tsx`, `frontend/e2e/settings.spec.ts`

**Interfaces:**
- Consumes: GitHub App config endpoints and webhook config/delivery endpoints.
- Produces: admin App credential form (write-only), per-project webhook form (repo, branch filters, preview toggle, TTL), delivery history list.

- [ ] **Step 1: Add `frontend/src/api/githubApp.ts`**

```ts
import { apiGet, apiPost, apiPut } from './core'

export interface GitHubAppConfigPublic {
  app_id: string
  slug: string | null
  has_private_key: boolean
  has_webhook_secret: boolean
}

export interface WebhookConfigPublic {
  project_id: string
  repo_full_name: string
  enabled: boolean
  branch_filters: string[]
  preview_enabled: boolean
  preview_ttl_seconds: number
}

export interface WebhookDeliveryPublic {
  delivery_id: string
  event: string
  action: string | null
  branch: string | null
  status: string
  received_at: string
  error: string | null
}

export const getGithubAppConfig = () => apiGet<GitHubAppConfigPublic>('/settings/github-app')
export const setGithubAppConfig = (body: { app_id: string; slug?: string; private_key: string; webhook_secret: string }) =>
  apiPut<GitHubAppConfigPublic>('/settings/github-app', body)
export const getWebhookConfig = (projectId: string) => apiGet<WebhookConfigPublic>(`/projects/${projectId}/github-webhook`)
export const setWebhookConfig = (projectId: string, body: Partial<WebhookConfigPublic>) =>
  apiPut<WebhookConfigPublic>(`/projects/${projectId}/github-webhook`, body)
export const listWebhookDeliveries = (projectId: string) =>
  apiGet<WebhookDeliveryPublic[]>(`/projects/${projectId}/github-webhook/deliveries`)
```

Re-export from `frontend/src/api/client.ts`.

- [ ] **Step 2: Create `frontend/src/pages/settings/GitHubAppCard.tsx`** — an admin-only card with App id, slug, PEM textarea, webhook-secret input, and a Save button. Show `has_private_key` / `has_webhook_secret` as `role="status"` text and never render the stored values. Use the LlmProviderCard write-only pattern and a `role="alert"` error banner from `formatApiError`. Add it to the Integrations section of `SettingsPage.tsx` behind the admin role check.

- [ ] **Step 3: Create `frontend/src/pages/teams/WebhookSettings.tsx`** — owner-only section for a project: repository name, enabled checkbox, branch filters (comma-separated), preview toggle, TTL input, Save button, and a deliveries table (event, branch, status, received at, error). Import `./webhook-settings.css`; use tokens only. Mount it from `TeamDetail.tsx` next to the compute-quota section.

- [ ] **Step 4: E2E** — extend `frontend/e2e/settings.spec.ts` with an admin case that saves App metadata and asserts the masked status text; extend `frontend/e2e/teams.spec.ts` with an owner case that enables a webhook for `org/repo`, adds a branch filter, and sees the saved values after reload.

- [ ] **Step 5: Verify and commit**

```bash
cd frontend && npm run typecheck && npm run lint && npm run build && npm run test:e2e -- e2e/settings.spec.ts && npm run test:e2e -- e2e/teams.spec.ts
```

```bash
git add frontend/src/api/githubApp.ts frontend/src/api/client.ts frontend/src/pages/settings/GitHubAppCard.tsx frontend/src/pages/SettingsPage.tsx frontend/src/pages/teams/WebhookSettings.tsx frontend/src/pages/teams/webhook-settings.css frontend/src/pages/teams/TeamDetail.tsx frontend/e2e/settings.spec.ts frontend/e2e/teams.spec.ts
git commit -m "feat(ui): add GitHub App and webhook settings"
```

---

### Task 6: F10 — PR preview deploys, TTL GC and secret guard

**Files:**
- Modify: `backend/app/api/routes/webhooks.py`, `backend/app/core/traffic/public_route_host.py`, `backend/app/api/app.py`, `backend/app/core/deploy/github_auth.py`
- Create: `backend/app/core/previews.py`, `frontend/src/api/previews.ts`, `frontend/src/pages/teams/PreviewSettings.tsx` (or fold into `WebhookSettings.tsx`), `frontend/e2e/previews.spec.ts`
- Test: `backend/tests/test_previews.py`

**Interfaces:**
- Consumes: `spawn_deploy_worker`, `runtime_config_with_secrets(allow_secrets=False)`, `allocate_public_hostname`, `PreviewDeploy`.
- Produces: `enqueue_preview_deploy(...)`, `collect_expired_previews(...)`, `GET /api/projects/{id}/previews`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_previews.py`

```python
import pytest
from app.core.previews import preview_deploy_config, collect_expired_previews
from app.core.exceptions import PreviewSecretForbiddenError
from app.db.models import PreviewDeploy


def test_preview_config_is_capped_and_namespaced() -> None:
    config = preview_deploy_config(
        repo_full_name="org/repo", pr_number=7, head_sha="abc123",
        image="nginx:latest", env_vars={"PUBLIC_URL": "https://example.test"},
        ttl_seconds=600,
    )
    assert config.name.startswith("pr-7-")
    assert config.cpu_limit is not None and config.cpu_limit <= 0.5
    assert config.memory_limit is not None and config.memory_limit <= 512
    assert config.public_route is True
    assert "PREVIEW=true" in "=".join(f"{k}={v}" for k, v in config.labels.items())


def test_preview_rejects_secret_reference() -> None:
    with pytest.raises(PreviewSecretForbiddenError):
        preview_deploy_config(
            repo_full_name="org/repo", pr_number=8, head_sha="def", image="nginx",
            env_vars={"DB": "secret://DB_URL"}, ttl_seconds=600,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_previews.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `backend/app/core/previews.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PreviewSecretForbiddenError
from app.core.models import DeployConfig
from app.core.secret_store import parse_secret_reference
from app.db.models import PreviewDeploy

PREVIEW_CPU_LIMIT_CORES = 0.5
PREVIEW_MEMORY_LIMIT_MB = 512


def preview_deploy_config(
    *, repo_full_name: str, pr_number: int, head_sha: str, image: str,
    env_vars: dict[str, str], ttl_seconds: int,
) -> DeployConfig:
    for key, value in env_vars.items():
        if parse_secret_reference(value) is not None:
            raise PreviewSecretForbiddenError(f"Secret reference in env key {key!r} is not allowed for previews")
    return DeployConfig(
        image=image,
        name=f"pr-{pr_number}-{head_sha[:8]}",
        env_vars={"PREVIEW": "true", "PREVIEW_PR": str(pr_number), **env_vars},
        cpu_limit=PREVIEW_CPU_LIMIT_CORES,
        memory_limit=PREVIEW_MEMORY_LIMIT_MB,
        public_route=True,
        labels={"PREVIEW": "true", "PREVIEW_REPO": repo_full_name},
    )


async def collect_expired_previews(
    session: AsyncSession, orchestrator, traffic_router,
) -> int:
    now = datetime.now(UTC)
    rows = (await session.execute(
        select(PreviewDeploy).where(PreviewDeploy.expires_at <= now, PreviewDeploy.closed_at.is_(None))
    )).scalars().all()
    for row in rows:
        if row.container_id:
            await orchestrator.remove(row.container_id, force=True)
        if row.route_host:
            await traffic_router.remove_route(row.container_name or row.route_host)
        row.status = "expired"
        row.closed_at = now
    await session.commit()
    return len(rows)
```

In `preview_deploy_config`, apply the preview hostname prefix by passing `label_prefix="pr-"` where `allocate_public_hostname` is called in the webhook path (public route allocation is handled by `apply_public_route_to_deploy_config`, so pass the prefix there).

- [ ] **Step 4: Wire the webhook to enqueue previews** in `backend/app/api/routes/webhooks.py`

For `pull_request` events with `action in {"opened", "synchronize", "reopened"}` and `config.preview_enabled`:
- reject fork PRs with any `secret://` env value before enqueueing (the shared `preview_deploy_config` already rejects all refs);
- call `preview_deploy_config(...)` with the PR head SHA and a dedicated env set (no production env keys — use an allowlist configured on `GitHubWebhookConfig` or an empty set by default);
- get `token = await github_token_for_project(session, project_id, user)`;
- create a `PreviewDeploy` row with `expires_at = now + ttl`, unique `(project_id, repo, pr_number)` (upsert on synchronize);
- call `spawn_deploy_worker(registry, job_id, worker, ...)` using the existing `_run_container_deploy_worker` with a `RunFromSourceRequest` built from the preview config, and mark the row `deployed` on success.
- For `action == "closed"`, set `closed_at`, remove the container and route, and mark the row `closed`.

- [ ] **Step 5: Start the GC loop** in `backend/app/api/app.py` alongside `run_monitoring_loop` inside the `VELA_BACKGROUND_LOOPS_ENABLED` gate from Group B:

```python
async def run_preview_gc_loop(session_factory) -> None:
    while True:
        try:
            async with session_factory() as session:
                await collect_expired_previews(
                    session, get_orchestrator(), get_traffic_router(),
                )
        except Exception:
            logger.exception("Preview GC cycle failed")
        await asyncio.sleep(60)
```

Register it in the lifespan and cancel it on shutdown. Add `GET /api/projects/{id}/previews` to `backend/app/api/routes/projects.py` returning `PreviewDeploy` rows scoped by `require_membership`.

- [ ] **Step 6: Frontend** — add `frontend/src/api/previews.ts` with `listPreviews(projectId)` and a small preview list in the project's WebhookSettings/PreviewSettings section (PR number, URL, expiry, status, revoke). Add `frontend/e2e/previews.spec.ts` asserting the preview settings toggle is visible to an owner and that a seeded preview row renders its URL.

- [ ] **Step 7: Verify and commit**

```bash
cd backend && python -m pytest tests/test_previews.py tests/test_webhooks.py -q && ruff check . && mypy app/ tests/
cd ../frontend && npm run typecheck && npm run lint && npm run build && npm run test:e2e -- e2e/previews.spec.ts
```

```bash
git add backend/app/core/previews.py backend/app/api/routes/webhooks.py backend/app/core/traffic/public_route_host.py backend/app/api/app.py backend/app/api/routes/projects.py frontend/src/api/previews.ts frontend/src/pages/teams frontend/e2e/previews.spec.ts backend/tests/test_previews.py
git commit -m "feat(previews): add TTL-bound PR preview deploys"
```

---

## Self-review (done at plan authoring)

- **Spec coverage:** F14 → Tasks 1–2; F13 → Task 3; F15 → Tasks 4–5; F10 → Task 6. All locked decisions represented: write-only versioned secrets, runtime-only resolution, dry-run + in-place redeploy, GitHub App installation tokens, signed/deduped webhooks, repo opt-in, preview caps/TTL/no-secrets/health+monitor GC.
- **Placeholder scan:** no TBD/TODO. Task 4 Step 2 has one explicit in-code note about the unique-key lookup shape (`delivery_id` is the unique column, not the PK) and Task 1 Step 2 lists all tables the single migration creates; neither defers work.
- **Type consistency:** `resolve_secret_reference` from Task 1 is consumed by Task 2; `runtime_config_with_secrets` from Task 2 is reused by Tasks 3 and 6; `verify_github_signature` and `installation_token` from Task 4 are consumed by the webhook and preview paths; `PreviewDeploy` from Task 1 is used by Task 6. Migration `0026` targets Group B's `0025` head with a merge-time check, avoiding a second head.
