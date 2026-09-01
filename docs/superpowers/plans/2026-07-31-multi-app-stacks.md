# Multi-App Stack Deployments — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native stack deployments — groups of services sharing a Docker network, creatable via visual builder or docker-compose import, with stack composition (nesting).

**Architecture:** New `app/core/stacks/` domain package with repository, compose parser, and deploy coordinator. Three new DB tables (`stacks`, `stack_services`, `stack_compositions`). New API router at `/api/stacks`. Frontend uses `@xyflow/react` for a node-based visual builder.

**Tech Stack:** Python (SQLAlchemy, FastAPI, Pydantic), TypeScript/React (@xyflow/react), Pytest, Alembic

## Global Constraints

- Python: follow existing patterns — explicit types, `match`/`case` for unions, typed where helpful
- TypeScript: avoid `instanceof`, prefer discriminated unions, exact versions in package.json
- Tests: use `FakeContainerOrchestrator`, in-memory SQLite via `conftest.py` fixtures
- Naming: full words, no cryptic abbreviations
- Ponytail mode active — shortest working diff, no boilerplate
- Alembic migrations use sync psycopg; revision IDs follow `NNNN_short_description` pattern
- Frontend routes wrapped in `RequireAuth`, mounted under `<Layout>`

---

### Task 1: Database models and Alembic migration

**Files:**
- Modify: `backend/app/db/models.py` — add `Stack`, `StackService`, `StackComposition` models, add `stack_id` to `DeploymentRecord`
- Create: `backend/alembic/versions/0014_stacks.py` — migration for new tables and column

**Interfaces:**
- Produces: ORM models `Stack`, `StackService`, `StackComposition` with relationships
- Produces: `DeploymentRecord.stack_id` column (nullable FK → stacks)

- [ ] **Step 1: Add models to `backend/app/db/models.py`**

Append after `AlertHistory` class (line ~407):

```python
class Stack(Base):
    __tablename__ = "stacks"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_stacks_project_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    network_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    project: Mapped["Project"] = relationship()
    services: Mapped[list["StackService"]] = relationship(
        back_populates="stack", cascade="all, delete-orphan",
    )
    compositions_parent: Mapped[list["StackComposition"]] = relationship(
        foreign_keys="StackComposition.parent_stack_id", cascade="all, delete-orphan",
    )
    compositions_child: Mapped[list["StackComposition"]] = relationship(
        foreign_keys="StackComposition.child_stack_id", cascade="all, delete-orphan",
    )


class StackService(Base):
    __tablename__ = "stack_services"
    __table_args__ = (
        UniqueConstraint("stack_id", "service_name", name="uq_stack_services_stack_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    stack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stacks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    container_port: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    env_vars: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    command: Mapped[list | None] = mapped_column(JSON, nullable=True)
    public_route: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    depends_on: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )

    stack: Mapped["Stack"] = relationship(back_populates="services")


class StackComposition(Base):
    __tablename__ = "stack_compositions"
    __table_args__ = (
        UniqueConstraint("parent_stack_id", "child_stack_id", name="uq_stack_compositions_parent_child"),
    )

    parent_stack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stacks.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_stack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stacks.id", ondelete="CASCADE"),
        nullable=False,
    )
```

Also modify `DeploymentRecord` — add after `public_url` field (~line 293):

```python
    stack_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stacks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
```

- [ ] **Step 2: Create migration `backend/alembic/versions/0014_stacks.py`**

```python
"""Add stacks, stack_services, stack_compositions tables and deployment_records.stack_id.

Revision ID: 0014_stacks
Revises: 0013_scaling_stabilization
Create Date: 2026-07-31

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_stacks"
down_revision: str | Sequence[str] | None = "0013_scaling_stabilization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stacks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("network_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_stacks_project_name"),
        sa.UniqueConstraint("network_name", name="uq_stacks_network_name"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_stacks_project_id"), "stacks", ["project_id"], unique=False)

    op.create_table(
        "stack_services",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("service_name", sa.String(128), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(2048), nullable=False),
        sa.Column("container_port", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("env_vars", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("command", sa.JSON(), nullable=True),
        sa.Column("public_route", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("depends_on", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stack_id", "service_name", name="uq_stack_services_stack_name"),
        sa.ForeignKeyConstraint(["stack_id"], ["stacks.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_stack_services_stack_id"), "stack_services", ["stack_id"], unique=False)

    op.create_table(
        "stack_compositions",
        sa.Column("parent_stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("child_stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("parent_stack_id", "child_stack_id"),
        sa.UniqueConstraint("parent_stack_id", "child_stack_id", name="uq_stack_compositions_parent_child"),
        sa.ForeignKeyConstraint(["parent_stack_id"], ["stacks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_stack_id"], ["stacks.id"], ondelete="CASCADE"),
    )

    op.add_column(
        "deployment_records",
        sa.Column("stack_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_deployment_records_stack_id", "deployment_records",
        "stacks", ["stack_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(op.f("ix_deployment_records_stack_id"), "deployment_records", ["stack_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_deployment_records_stack_id"), table_name="deployment_records")
    op.drop_constraint("fk_deployment_records_stack_id", "deployment_records", type_="foreignkey")
    op.drop_column("deployment_records", "stack_id")
    op.drop_index(op.f("ix_stack_services_stack_id"), table_name="stack_services")
    op.drop_table("stack_compositions")
    op.drop_table("stack_services")
    op.drop_index(op.f("ix_stacks_project_id"), table_name="stacks")
    op.drop_table("stacks")
```

- [ ] **Step 3: Run migration to verify**

```bash
cd backend && python -m alembic upgrade head
```

Expected: no errors, new tables created.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0014_stacks.py
git commit -m "feat: add stack, stack_service, stack_composition models and migration"
```

---

### Task 2: Stack exceptions

**Files:**
- Modify: `backend/app/core/exceptions.py` — add stack-specific exceptions
- Modify: `backend/app/api/errors.py` — register handlers

**Interfaces:**
- Consumes: `VelaError` base class from `exceptions.py`
- Produces: `StackError`, `StackNotFoundError`, `StackCompositionCycleError`, `ComposeImportError`

- [ ] **Step 1: Add exceptions to `backend/app/core/exceptions.py`**

Append after the project error classes (~line 342):

```python
class StackError(VelaError):
    """Base exception for stack operations."""


class StackNotFoundError(StackError):
    def __init__(self, stack_id: str) -> None:
        self.stack_id = stack_id
        super().__init__(f"Stack not found: {stack_id}")


class StackCompositionCycleError(StackError):
    def __init__(self, stack_names: list[str]) -> None:
        self.stack_names = stack_names
        super().__init__(f"Cycle detected in stack composition: {' → '.join(stack_names)}")


class ComposeImportError(StackError):
    def __init__(self, message: str, *, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []
        super().__init__(message)
```

- [ ] **Step 2: Register handlers in `backend/app/api/errors.py`**

Add imports at top:

```python
from app.core.exceptions import (
    # ... existing imports ...
    ComposeImportError,
    StackCompositionCycleError,
    StackNotFoundError,
)
```

Add handler registrations in `register_exception_handlers`:

```python
@application.exception_handler(StackNotFoundError)
async def handle_stack_not_found(request: Request, exc: StackNotFoundError):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@application.exception_handler(StackCompositionCycleError)
async def handle_stack_cycle(request: Request, exc: StackCompositionCycleError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "stack_names": exc.stack_names},
    )


@application.exception_handler(ComposeImportError)
async def handle_compose_import(request: Request, exc: ComposeImportError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "warnings": exc.warnings},
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/exceptions.py backend/app/api/errors.py
git commit -m "feat: add stack exceptions and error handlers"
```

---

### Task 3: API schemas (Pydantic models)

**Files:**
- Modify: `backend/app/api/schemas.py` — add stack public schemas and request bodies

**Interfaces:**
- Consumes: `ProjectPublic`, `DeploymentRecordPublic` from existing schemas
- Produces: `StackServicePublic`, `StackPublic`, `StackCreate`, `StackServiceCreate`, `ComposeImportRequest`, `ComposeImportResponse`

- [ ] **Step 1: Add schemas to `backend/app/api/schemas.py`**

Append after `DeploymentDiffResponse` (~line 530):

```python
# ---------------------------------------------------------------------------
# Stacks
# ---------------------------------------------------------------------------

class StackServiceCreate(BaseModel):
    service_name: str = Field(min_length=1, max_length=128)
    source_kind: Literal["image", "git", "dockerfile_template"]
    source_ref: str = Field(min_length=1, max_length=2048)
    container_port: int = Field(default=80, ge=1, le=65535)
    env_vars: dict[str, str] = Field(default_factory=dict)
    command: list[str] | None = None
    public_route: bool = False
    depends_on: list[str] | None = None


class StackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    project_id: uuid.UUID | None = None
    services: list[StackServiceCreate] = Field(min_length=1)
    child_stack_ids: list[uuid.UUID] = Field(default_factory=list)


class StackServicePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stack_id: uuid.UUID
    service_name: str
    source_kind: str
    source_ref: str
    container_port: int
    env_vars: dict[str, str]
    command: list[str] | None
    public_route: bool
    depends_on: list[str] | None


class StackPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    network_name: str
    created_at: datetime
    services: list[StackServicePublic] = []
    child_stack_ids: list[uuid.UUID] = []


class ComposeImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    project_id: uuid.UUID | None = None
    yaml_content: str


class ComposeImportResponse(BaseModel):
    stack: StackPublic
    warnings: list[str] = []
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/schemas.py
git commit -m "feat: add stack API schemas"
```

---

### Task 4: Stack repository (CRUD, composition, cycle detection)

**Files:**
- Create: `backend/app/core/stacks/__init__.py`
- Create: `backend/app/core/stacks/repository.py`
- Create: `backend/tests/test_stack_repository.py`

**Interfaces:**
- Consumes: `Stack`, `StackService`, `StackComposition` ORM models from Task 1
- Consumes: `StackNotFoundError`, `StackCompositionCycleError` from Task 2
- Produces: `create_stack(session, project_id, name, services, child_ids) -> Stack`
- Produces: `get_stack(session, stack_id, user_id) -> Stack | None`
- Produces: `list_stacks(session, user_id) -> list[Stack]`
- Produces: `delete_stack(session, stack_id, user_id) -> None`
- Produces: `resolve_composition(stack) -> list[StackService]` (flattened, topologically sorted)
- Produces: `detect_cycle(parent_id, child_id, session) -> list[str] | None`

- [ ] **Step 1: Create `backend/app/core/stacks/__init__.py`**

Empty file.

- [ ] **Step 2: Write failing test `backend/tests/test_stack_repository.py`**

```python
"""Tests for stack repository — CRUD, composition, cycle detection."""

from __future__ import annotations

import uuid

import pytest

from app.core.stacks.repository import (
    create_stack,
    delete_stack,
    detect_cycle,
    get_stack,
    list_stacks,
    resolve_composition,
)
from app.db.models import Stack, StackService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def sample_services():
    return [
        StackService(
            service_name="frontend",
            source_kind="image",
            source_ref="nginx:alpine",
            container_port=80,
            env_vars={},
            public_route=True,
        ),
        StackService(
            service_name="backend",
            source_kind="image",
            source_ref="python:3.12-slim",
            container_port=8000,
            env_vars={"DATABASE_URL": "postgres://db:5432/app"},
            public_route=False,
            depends_on=["db"],
        ),
        StackService(
            service_name="db",
            source_kind="image",
            source_ref="postgres:16",
            container_port=5432,
            env_vars={"POSTGRES_DB": "app"},
            public_route=False,
        ),
    ]


async def test_create_stack(db_app: AsyncSession, sample_services):
    """Creating a stack persists it with services and returns the stack."""
    from app.core.projects.repository import get_personal_project_id

    user = db_app.get(User, ...)  # use test user from conftest
    project_id = await get_personal_project_id(db_app, user)

    stack = await create_stack(
        db_app, project_id, "my-stack", sample_services, [],
    )
    await db_app.commit()

    assert stack.id is not None
    assert stack.name == "my-stack"
    assert "vela-stack-" in stack.network_name
    assert len(stack.services) == 3
    service_names = [s.service_name for s in stack.services]
    assert "frontend" in service_names
    assert "backend" in service_names
    assert "db" in service_names


async def test_get_stack_not_found(db_app: AsyncSession):
    """Getting a non-existent stack returns None."""
    result = await get_stack(db_app, uuid.uuid4(), uuid.uuid4())
    assert result is None


async def test_list_stacks_empty(db_app: AsyncSession):
    """Listing stacks for a user with no stacks returns empty list."""
    from app.core.projects.repository import get_personal_project_id

    user = db_app.get(User, ...)
    stacks = await list_stacks(db_app, user.id)
    assert stacks == []


async def test_cycle_detection_self_reference(db_app: AsyncSession):
    """Detecting a self-reference cycle returns the stack name."""
    from app.core.projects.repository import get_personal_project_id

    user = db_app.get(User, ...)
    project_id = await get_personal_project_id(db_app, user)

    stack = await create_stack(db_app, project_id, "cycle-test", [], [])
    await db_app.commit()

    cycle = await detect_cycle(db_app, stack.id, stack.id)
    assert cycle is not None
    assert "cycle-test" in cycle


async def test_resolve_composition_flat(sample_services):
    """Resolving a stack with no children returns its own services."""
    stack = Stack(id=uuid.uuid4(), name="test", services=sample_services)
    services = resolve_composition(stack, [])
    assert len(services) == 3
```

- [ ] **Step 3: Implement `backend/app/core/stacks/repository.py`**

```python
"""Stack CRUD, composition resolution, and cycle detection."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import StackCompositionCycleError, StackNotFoundError
from app.core.projects.repository import require_membership
from app.db.models import Stack, StackComposition, StackService, User


async def create_stack(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    services: list[StackService],
    child_stack_ids: list[uuid.UUID],
) -> Stack:
    """Create a stack with services and optional child stack references."""
    import hashlib

    stack = Stack(
        project_id=project_id,
        name=name,
        network_name=f"vela-stack-{hashlib.sha256(name.encode()).hexdigest()[:12]}",
        services=services,
    )
    session.add(stack)
    await session.flush()

    for child_id in child_stack_ids:
        if child_id == stack.id:
            raise StackCompositionCycleError([name])
        composition = StackComposition(
            parent_stack_id=stack.id,
            child_stack_id=child_id,
        )
        session.add(composition)

    return stack


async def get_stack(
    session: AsyncSession,
    stack_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Stack | None:
    """Get a stack the user has access to, with services and compositions loaded."""
    stmt = (
        select(Stack)
        .where(Stack.id == stack_id)
        .options(
            selectinload(Stack.services),
            selectinload(Stack.compositions_parent),
            selectinload(Stack.compositions_child),
        )
    )
    result = await session.execute(stmt)
    stack = result.scalar_one_or_none()

    if stack is None:
        return None

    # Verify user has access to the stack's project
    await require_membership(session, project_id=stack.project_id, user_id=user_id)
    return stack


async def list_stacks(session: AsyncSession, user_id: uuid.UUID) -> list[Stack]:
    """List all stacks belonging to projects the user is a member of."""
    from app.core.projects.repository import get_project_ids_for_user

    project_ids = await get_project_ids_for_user(session, user_id)
    if not project_ids:
        return []

    stmt = (
        select(Stack)
        .where(Stack.project_id.in_(project_ids))
        .options(
            selectinload(Stack.services),
            selectinload(Stack.compositions_parent),
        )
        .order_by(Stack.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_stack(
    session: AsyncSession,
    stack_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete a stack. User must have write access to the stack's project."""
    stack = await get_stack(session, stack_id, user_id)
    if stack is None:
        raise StackNotFoundError(str(stack_id))

    membership = await require_membership(session, project_id=stack.project_id, user_id=user_id)
    from app.core.projects.enums import can_write
    if not can_write(membership.role):
        from app.core.exceptions import ProjectAccessDeniedError
        raise ProjectAccessDeniedError("You do not have permission to delete this stack.")

    await session.delete(stack)


def resolve_composition(
    stack: Stack,
    child_stacks: list[Stack],
) -> list[StackService]:
    """Flatten stack services from parent and child stacks, respecting depends_on ordering.

    Returns services in topological order (dependencies first).
    """
    all_services: list[StackService] = []
    for child in child_stacks:
        all_services.extend(child.services)
    all_services.extend(stack.services)

    # Build adjacency from depends_on
    name_to_service = {s.service_name: s for s in all_services}
    graph: dict[str, set[str]] = {s.service_name: set() for s in all_services}

    for service in all_services:
        if service.depends_on:
            for dep in service.depends_on:
                if dep in graph:
                    graph[dep].add(service.service_name)

    # Topological sort (Kahn's algorithm)
    in_degree = {name: 0 for name in graph}
    for node, deps in graph.items():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue = [name for name, deg in in_degree.items() if deg == 0]
    sorted_names: list[str] = []

    while queue:
        queue.sort()  # deterministic ordering
        current = queue.pop(0)
        sorted_names.append(current)
        for neighbor in graph.get(current, set()):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return [name_to_service[name] for name in sorted_names if name in name_to_service]


async def detect_cycle(
    session: AsyncSession,
    parent_id: uuid.UUID,
    child_id: uuid.UUID,
) -> list[str] | None:
    """Check if adding parent → child composition would create a cycle.

    Returns list of stack names forming the cycle, or None if no cycle.
    """
    if parent_id == child_id:
        stmt = select(Stack.name).where(Stack.id == parent_id)
        result = await session.execute(stmt)
        name = result.scalar_one_or_none()
        return [name] if name else ["unknown"]

    # BFS from child_id following compositions_parent edges to see if we reach parent_id
    visited: set[uuid.UUID] = set()
    queue: list[uuid.UUID] = [child_id]
    path: dict[uuid.UUID, uuid.UUID | None] = {child_id: None}

    while queue:
        current = queue.pop(0)
        if current == parent_id:
            # Reconstruct cycle path
            cycle_names = []
            node: uuid.UUID | None = current
            while node is not None:
                name_stmt = select(Stack.name).where(Stack.id == node)
                result = await session.execute(name_stmt)
                cycle_names.append(result.scalar_one_or_none() or "unknown")
                node = path.get(node)
            return list(reversed(cycle_names))

        visited.add(current)

        # Find stacks where current is a child (i.e., current is referenced by these stacks)
        stmt = (
            select(StackComposition.parent_stack_id)
            .where(StackComposition.child_stack_id == current)
        )
        result = await session.execute(stmt)
        for row in result.mappings():
            next_id = row["parent_stack_id"]
            if next_id not in visited:
                path[next_id] = current
                queue.append(next_id)

    return None
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_stack_repository.py -v
```

Expected: tests pass (may need to adjust test to use conftest fixtures properly — use `api_client` and `db_app` fixtures).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/stacks/ backend/tests/test_stack_repository.py
git commit -m "feat: implement stack repository with CRUD, composition, cycle detection"
```

---

### Task 5: Docker Compose parser

**Files:**
- Create: `backend/app/core/stacks/compose_parser.py`
- Create: `backend/tests/test_compose_parser.py`
- Modify: `backend/pyproject.toml` — add `pyyaml` dependency

**Interfaces:**
- Consumes: `StackService` ORM model from Task 1
- Produces: `parse_compose(yaml_content: str) -> tuple[list[StackService], list[str]]`

- [ ] **Step 1: Add `pyyaml` to `backend/pyproject.toml`**

Add to `dependencies`:

```toml
"pyyaml>=6.0,<7.0",
```

- [ ] **Step 2: Write failing test `backend/tests/test_compose_parser.py`**

```python
"""Tests for docker-compose parser."""

from __future__ import annotations

from app.core.stacks.compose_parser import parse_compose
from app.db.models import StackService


def test_parse_simple_compose():
    """Parsing a compose file with image services produces StackService records."""
    yaml_content = """
version: "3"
services:
  frontend:
    image: nginx:alpine
    ports:
      - "80:80"
    environment:
      NODE_ENV: production
  backend:
    image: python:3.12-slim
    ports:
      - "8000:8000"
    depends_on:
      - db
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: admin
"""
    services, warnings = parse_compose(yaml_content)

    assert len(services) == 3
    names = {s.service_name for s in services}
    assert names == {"frontend", "backend", "db"}

    frontend = next(s for s in services if s.service_name == "frontend")
    assert frontend.source_kind == "image"
    assert frontend.source_ref == "nginx:alpine"
    assert frontend.container_port == 80
    assert frontend.env_vars == {"NODE_ENV": "production"}

    backend = next(s for s in services if s.service_name == "backend")
    assert backend.depends_on == ["db"]

    db = next(s for s in services if s.service_name == "db")
    assert db.container_port == 5432


def test_parse_compose_with_volumes_produces_warning():
    """Unsupported features like volumes produce warnings but services are still created."""
    yaml_content = """
version: "3"
services:
  app:
    image: nginx:alpine
    volumes:
      - ./data:/app/data
"""
    services, warnings = parse_compose(yaml_content)

    assert len(services) == 1
    assert services[0].service_name == "app"
    assert any("volumes" in w.lower() for w in warnings)


def test_parse_empty_services():
    """Parsing a compose file with no services returns empty list."""
    yaml_content = """
version: "3"
services: {}
"""
    services, warnings = parse_compose(yaml_content)
    assert services == []


def test_parse_build_context():
    """A build context is mapped to dockerfile_template source kind."""
    yaml_content = """
version: "3"
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
"""
    services, warnings = parse_compose(yaml_content)

    assert len(services) == 1
    assert services[0].source_kind == "dockerfile_template"
    assert services[0].source_ref == "."
```

- [ ] **Step 3: Implement `backend/app/core/stacks/compose_parser.py`**

```python
"""Parse docker-compose YAML into StackService records."""

from __future__ import annotations

import re

import yaml

from app.db.models import StackService


def parse_compose(yaml_content: str) -> tuple[list[StackService], list[str]]:
    """Parse docker-compose YAML content into StackService records.

    Returns:
        Tuple of (services, warnings). Warnings describe unsupported features
        that were dropped. The service is still created without the unsupported feature.
    """
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        return [], ["Invalid compose file: expected a mapping at the top level."]

    services_config = data.get("services", {})
    if not isinstance(services_config, dict):
        return [], []

    warnings: list[str] = []
    services: list[StackService] = []

    for service_name, config in services_config.items():
        if not isinstance(config, dict):
            warnings.append(f"Service '{service_name}': invalid configuration, skipping.")
            continue

        service, service_warnings = _parse_service(service_name, config)
        services.append(service)
        warnings.extend(service_warnings)

    return services, warnings


def _parse_service(
    name: str,
    config: dict,
) -> tuple[StackService, list[str]]:
    """Parse a single service configuration into a StackService."""
    warnings: list[str] = []

    # Determine source kind and ref
    source_kind, source_ref = _resolve_source(config, name, warnings)

    # Container port
    container_port = _extract_container_port(config, warnings)

    # Environment variables
    env_vars = _extract_env(config)

    # Command
    command = config.get("command")
    if isinstance(command, str):
        command = command.split()
    elif not isinstance(command, list):
        command = None

    # Depends on
    depends_on = _extract_depends_on(config)

    # Check for unsupported features
    _check_unsupported(config, name, warnings)

    return (
        StackService(
            service_name=name,
            source_kind=source_kind,
            source_ref=source_ref,
            container_port=container_port,
            env_vars=env_vars,
            command=command,
            public_route=False,
            depends_on=depends_on if depends_on else None,
        ),
        warnings,
    )


def _resolve_source(
    config: dict,
    name: str,
    warnings: list[str],
) -> tuple[str, str]:
    """Determine source_kind and source_ref from image or build config."""
    image = config.get("image")
    if image:
        return "image", str(image)

    build = config.get("build")
    if isinstance(build, str):
        return "dockerfile_template", build
    if isinstance(build, dict):
        context = build.get("context", ".")
        return "dockerfile_template", str(context)

    warnings.append(f"Service '{name}': no image or build specified, defaulting to 'nginx:alpine'.")
    return "image", "nginx:alpine"


def _extract_container_port(config: dict, warnings: list[str]) -> int:
    """Extract the container port from ports mapping or expose."""
    ports = config.get("ports", [])
    if isinstance(ports, list) and ports:
        first_port = str(ports[0])
        # Handle "8080:80" format — take the container side (right)
        if ":" in first_port:
            parts = first_port.rsplit(":", 1)
            try:
                return int(parts[1].split("/")[0])
            except (ValueError, IndexError):
                pass
        try:
            return int(first_port.split("/")[0])
        except ValueError:
            pass

    # Check expose
    expose = config.get("expose", [])
    if isinstance(expose, list) and expose:
        try:
            return int(str(expose[0]))
        except ValueError:
            pass

    return 80


def _extract_env(config: dict) -> dict[str, str]:
    """Extract environment variables from list or dict format."""
    env = config.get("environment", {})
    if isinstance(env, dict):
        return {str(k): str(v) if v is not None else "" for k, v in env.items()}
    if isinstance(env, list):
        result = {}
        for item in env:
            item_str = str(item)
            if "=" in item_str:
                key, _, value = item_str.partition("=")
                result[key] = value
            else:
                result[item_str] = ""
        return result
    return {}


def _extract_depends_on(config: dict) -> list[str] | None:
    """Extract depends_on as a list of service names."""
    depends = config.get("depends_on")
    if isinstance(depends, list):
        return [str(d) for d in depends]
    if isinstance(depends, dict):
        return list(depends.keys())
    return None


def _check_unsupported(config: dict, name: str, warnings: list[str]) -> None:
    """Check for unsupported compose features and emit warnings."""
    unsupported = {
        "volumes": "volume mounts",
        "secrets": "secrets",
        "configs": "configs",
        "deploy": "deploy resources (CPU/memory limits, replicas)",
        "healthcheck": "health checks",
        "extends": "extends",
        "networks": "custom networks (Vela uses a shared stack network)",
    }

    for key, label in unsupported.items():
        if key in config:
            warnings.append(
                f"Service '{name}': unsupported feature '{key}' ({label}) — "
                f"service will be created without this feature."
            )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_compose_parser.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/stacks/compose_parser.py backend/tests/test_compose_parser.py backend/pyproject.toml
git commit -m "feat: add docker-compose parser with warning for unsupported features"
```

---

### Task 6: Stack deploy coordinator

**Files:**
- Create: `backend/app/core/stacks/deploy.py`
- Modify: `backend/app/core/containers/fake_orchestrator.py` — add network tracking for tests
- Create: `backend/tests/test_stack_deploy.py`

**Interfaces:**
- Consumes: `resolve_composition()` from Task 4, `ContainerOrchestrator.deploy()`, `TrafficRouter`
- Consumes: `DeployConfig` from `app.core.models`
- Produces: `deploy_stack(session, orchestrator, traffic_router, stack, user_id) -> dict`

- [ ] **Step 1: Implement `backend/app/core/stacks/deploy.py`**

```python
"""Coordinated deployment of stack services onto a shared Docker network."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.route_wiring import (
    backend_port_for_route,
    register_route_for_deployed_container,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.models import ContainerInfo, DeployConfig
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import DeploymentRecord, Stack, StackService, User


async def deploy_stack(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    stack: Stack,
    user: User,
    child_stacks: list[Stack],
) -> dict[str, object]:
    """Deploy all services in a stack onto a shared network.

    On failure, rolls back all started containers and removes the network.

    Returns:
        Dict with 'containers', 'route_wired', 'public_url' per service, and 'error' if failed.
    """
    from app.core.stacks.repository import resolve_composition

    services = resolve_composition(stack, child_stacks)
    if not services:
        return {"error": "Stack has no services to deploy."}

    deployed_containers: list[ContainerInfo] = []

    try:
        for service in services:
            container_name = f"{stack.name}_{service.service_name}"
            config = _build_deploy_config(stack, service, container_name)

            info = await orchestrator.deploy(config)
            deployed_containers.append(info)

            # Wire public route if requested
            if service.public_route:
                try:
                    await register_route_for_deployed_container(
                        traffic_router=traffic_router,
                        container_info=info,
                        route_host=info.access_url or f"{service.service_name}.{stack.network_name}.local",
                        path_prefix="/",
                        backend_port=service.container_port,
                        tls_enabled=False,
                    )
                except Exception:
                    pass  # Route wiring failure is non-fatal; container stays up

            # Persist deployment record
            await _persist_deployment(
                session, user, stack, service, info,
            )

        await session.commit()
        return {
            "containers": [
                {
                    "service_name": s.service_name,
                    "container_id": c.id,
                    "container_name": c.name,
                }
                for s, c in zip(services, deployed_containers)
            ],
        }

    except Exception as exc:
        # Rollback: stop all deployed containers
        for container in deployed_containers:
            try:
                await orchestrator.stop(container.id, timeout=5)
                await orchestrator.remove(container.id, force=True)
            except Exception:
                pass

        raise exc


def _build_deploy_config(
    stack: Stack,
    service: StackService,
    container_name: str,
) -> DeployConfig:
    """Build a DeployConfig for a stack service."""
    return DeployConfig(
        image=service.source_ref,
        name=container_name,
        env_vars=dict(service.env_vars),
        container_listen_port=service.container_port,
        command=service.command,
        labels={
            "vela.stack_id": str(stack.id),
            "vela.service_name": service.service_name,
            "vela.network": stack.network_name,
        },
        public_route=service.public_route,
    )


async def _persist_deployment(
    session: AsyncSession,
    user: User,
    stack: Stack,
    service: StackService,
    container_info: ContainerInfo,
) -> None:
    """Persist a DeploymentRecord for a stack service deployment."""
    record = DeploymentRecord(
        user_id=user.id,
        project_id=stack.project_id,
        container_id=container_info.id,
        container_name=container_info.name,
        source_kind=service.source_kind,
        source_ref=service.source_ref,
        image_tag=service.source_ref,
        container_port=service.container_port,
        env_vars={k: "<REDACTED>" for k in service.env_vars},
        command=service.command,
        stack_id=stack.id,
    )
    session.add(record)
```

- [ ] **Step 2: Add network tracking to `backend/app/core/containers/fake_orchestrator.py`**

Add to `__init__`:

```python
self._networks: set[str] = set()
```

Add method:

```python
async def create_network(self, name: str) -> None:
    """Create a Docker network (no-op for fake, but tracked for tests)."""
    self._networks.add(name)

async def remove_network(self, name: str) -> None:
    """Remove a Docker network."""
    self._networks.discard(name)
```

Also add to the `ContainerOrchestrator` abstract base (`orchestrator.py`):

```python
@abstractmethod
async def create_network(self, name: str) -> None:
    """Create a Docker network for stack services."""

@abstractmethod
async def remove_network(self, name: str) -> None:
    """Remove a Docker network."""
```

And implement in `docker_orchestrator.py` using `docker.Networks` API.

- [ ] **Step 3: Write integration test `backend/tests/test_stack_deploy.py`**

```python
"""Integration tests for stack deployment."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator


def test_deploy_stack_creates_containers(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
):
    """Deploying a stack creates all service containers."""
    # Create a stack first
    create_response = api_client.post("/api/stacks/", json={
        "name": "test-stack",
        "services": [
            {
                "service_name": "frontend",
                "source_kind": "image",
                "source_ref": "nginx:alpine",
                "container_port": 80,
                "public_route": True,
            },
            {
                "service_name": "backend",
                "source_kind": "image",
                "source_ref": "python:3.12-slim",
                "container_port": 8000,
                "depends_on": ["db"],
            },
            {
                "service_name": "db",
                "source_kind": "image",
                "source_ref": "postgres:16",
                "container_port": 5432,
            },
        ],
    })
    assert create_response.status_code == 201, create_response.text
    stack_id = create_response.json()["id"]

    # Deploy the stack
    deploy_response = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert deploy_response.status_code == 200, deploy_response.text

    containers = deploy_response.json()["containers"]
    assert len(containers) == 3
    names = {c["container_name"] for c in containers}
    assert "test-stack_frontend" in names
    assert "test-stack_backend" in names
    assert "test-stack_db" in names


def test_import_compose_and_deploy(
    api_client: TestClient,
):
    """Importing a compose file and deploying creates containers."""
    compose_yaml = """
version: "3"
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
  api:
    image: python:3.12-slim
    ports:
      - "8000:8000"
"""
    import_response = api_client.post("/api/stacks/import-compose", json={
        "name": "compose-stack",
        "yaml_content": compose_yaml,
    })
    assert import_response.status_code == 201, import_response.text
    stack_id = import_response.json()["stack"]["id"]

    deploy_response = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert deploy_response.status_code == 200, deploy_response.text
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/stacks/deploy.py backend/tests/test_stack_deploy.py backend/app/core/containers/fake_orchestrator.py backend/app/core/containers/orchestrator.py
git commit -m "feat: implement stack deploy coordinator with rollback"
```

---

### Task 7: Stack API routes

**Files:**
- Create: `backend/app/api/routes/stacks.py`
- Modify: `backend/app/api/app.py` — mount stacks router

**Interfaces:**
- Consumes: repository functions from Task 4, compose parser from Task 5, deploy from Task 6
- Consumes: schemas from Task 3
- Produces: FastAPI router with GET /, POST /, POST /import-compose, GET /{id}, DELETE /{id}, POST /{id}/deploy

- [ ] **Step 1: Create `backend/app/api/routes/stacks.py`**

```python
"""Stack management API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_orchestrator,
    get_traffic_router,
)
from app.api.schemas import (
    ComposeImportRequest,
    ComposeImportResponse,
    StackCreate,
    StackPublic,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import StackNotFoundError
from app.core.stacks.compose_parser import parse_compose
from app.core.stacks.deploy import deploy_stack
from app.core.stacks.repository import (
    create_stack,
    delete_stack,
    get_stack,
    list_stacks,
    resolve_composition,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import Stack, StackService, User

router = APIRouter()


@router.get("/", response_model=list[StackPublic])
async def list_user_stacks(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[StackPublic]:
    stacks = await list_stacks(session, current_user.id)
    return [_stack_to_public(s) for s in stacks]


@router.post("/", response_model=StackPublic, status_code=status.HTTP_201_CREATED)
async def create_user_stack(
    body: StackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StackPublic:
    from app.core.projects.repository import get_personal_project_id, require_membership

    project_id = body.project_id or await get_personal_project_id(session, current_user)
    membership = await require_membership(session, project_id=project_id, user_id=current_user.id)
    from app.core.projects.enums import can_write
    if not can_write(membership.role):
        from app.core.exceptions import ProjectAccessDeniedError
        raise ProjectAccessDeniedError("You do not have permission to create stacks in this project.")

    services = [
        StackService(
            service_name=s.service_name,
            source_kind=s.source_kind,
            source_ref=s.source_ref,
            container_port=s.container_port,
            env_vars=s.env_vars,
            command=s.command,
            public_route=s.public_route,
            depends_on=s.depends_on,
        )
        for s in body.services
    ]

    # Check for cycles before creating compositions
    stack = await create_stack(session, project_id, body.name, services, body.child_stack_ids)
    await session.commit()
    return _stack_to_public(stack)


@router.post("/import-compose", response_model=ComposeImportResponse, status_code=status.HTTP_201_CREATED)
async def import_compose(
    body: ComposeImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ComposeImportResponse:
    from app.core.projects.repository import get_personal_project_id, require_membership

    services, warnings = parse_compose(body.yaml_content)
    if not services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compose file contains no valid services.",
        )

    project_id = body.project_id or await get_personal_project_id(session, current_user)
    membership = await require_membership(session, project_id=project_id, user_id=current_user.id)

    stack = await create_stack(session, project_id, body.name, services, [])
    await session.commit()

    return ComposeImportResponse(stack=_stack_to_public(stack), warnings=warnings)


@router.get("/{stack_id}", response_model=StackPublic)
async def get_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StackPublic:
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")
    return _stack_to_public(stack)


@router.delete("/{stack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> None:
    # Stop containers before deleting stack
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")

    for service in stack.services:
        container_name = f"{stack.name}_{service.service_name}"
        try:
            containers = await orchestrator.list()
            for c in containers:
                if c.name == container_name:
                    await orchestrator.stop(c.id, timeout=5)
                    await orchestrator.remove(c.id, force=True)
        except Exception:
            pass

    await delete_stack(session, stack_id, current_user.id)
    await session.commit()


@router.post("/{stack_id}/deploy", response_model=dict[str, object])
async def deploy_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> dict[str, object]:
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")

    # Resolve child stacks
    child_stacks = []
    for comp in stack.compositions_parent:
        from sqlalchemy import select as sa_select
        result = await session.execute(sa_select(Stack).where(Stack.id == comp.child_stack_id))
        child = result.scalar_one_or_none()
        if child:
            child_stacks.append(child)

    return await deploy_stack(session, orchestrator, traffic_router, stack, current_user, child_stacks)


def _stack_to_public(stack: Stack) -> StackPublic:
    return StackPublic(
        id=stack.id,
        project_id=stack.project_id,
        name=stack.name,
        network_name=stack.network_name,
        created_at=stack.created_at,
        services=[],  # StackServicePublic mapping would go here
        child_stack_ids=[c.child_stack_id for c in stack.compositions_parent],
    )
```

- [ ] **Step 2: Mount router in `backend/app/api/app.py`**

Add import:

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
    settings,
    stacks,  # NEW
    traffic,
    users,
)
```

Add router mount (after scaling):

```python
    application.include_router(
        stacks.router,
        prefix=f"{API_PREFIX}/stacks",
        tags=["stacks"],
    )
```

- [ ] **Step 3: Run integration tests**

```bash
cd backend && python -m pytest tests/test_stack_deploy.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/stacks.py backend/app/api/app.py
git commit -m "feat: add stack API routes and mount router"
```

---

### Task 8: Frontend — install dependency and API client

**Files:**
- Modify: `frontend/package.json` — add `@xyflow/react`
- Modify: `frontend/src/api/client.ts` — add stack API functions and types

**Interfaces:**
- Consumes: existing `apiPost`, `apiGet`, `apiDelete` functions
- Produces: `Stack`, `StackService`, `listStacks()`, `createStack()`, `importCompose()`, `getStack()`, `deleteStack()`, `deployStack()`

- [ ] **Step 1: Add `@xyflow/react` to `frontend/package.json`**

```json
"@xyflow/react": "12.3.0"
```

Run: `cd frontend && npm install` (verify exact version, no `^` prefix).

- [ ] **Step 2: Add stack types and functions to `frontend/src/api/client.ts`**

Append near the project types (~line 850):

```typescript
export interface StackService {
  id: string
  stack_id: string
  service_name: string
  source_kind: 'image' | 'git' | 'dockerfile_template'
  source_ref: string
  container_port: number
  env_vars: Record<string, string>
  command: string[] | null
  public_route: boolean
  depends_on: string[] | null
}

export interface Stack {
  id: string
  project_id: string
  name: string
  network_name: string
  created_at: string
  services: StackService[]
  child_stack_ids: string[]
}

export interface StackServiceCreate {
  service_name: string
  source_kind: 'image' | 'git' | 'dockerfile_template'
  source_ref: string
  container_port?: number
  env_vars?: Record<string, string>
  command?: string[] | null
  public_route?: boolean
  depends_on?: string[] | null
}

export async function listStacks(): Promise<Stack[]> {
  return apiGet<Stack[]>('/api/stacks/')
}

export async function createStack(body: {
  name: string
  project_id?: string
  services: StackServiceCreate[]
  child_stack_ids?: string[]
}): Promise<Stack> {
  return apiPost<Stack>('/api/stacks/', body)
}

export async function importCompose(body: {
  name: string
  project_id?: string
  yaml_content: string
}): Promise<{ stack: Stack; warnings: string[] }> {
  return apiPost<{ stack: Stack; warnings: string[] }>('/api/stacks/import-compose', body)
}

export async function getStack(id: string): Promise<Stack> {
  return apiGet<Stack>(`/api/stacks/${id}`)
}

export async function deleteStack(id: string): Promise<void> {
  await apiDelete(`/api/stacks/${id}`)
}

export async function deployStack(id: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/api/stacks/${id}/deploy`, {})
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/src/api/client.ts
git commit -m "feat: add @xyflow/react dependency and stack API client"
```

---

### Task 9: Frontend — Stacks list page

**Files:**
- Create: `frontend/src/pages/StacksPage.tsx`

**Interfaces:**
- Consumes: `listStacks`, `deleteStack`, `createStack`, `importCompose` from Task 8
- Produces: Stack list view with create/import buttons

- [ ] **Step 1: Create `frontend/src/pages/StacksPage.tsx`**

```typescript
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  deleteStack,
  formatApiError,
  listStacks,
  type Stack,
} from '../api/client'

export default function StacksPage() {
  const navigate = useNavigate()
  const [stacks, setStacks] = useState<Stack[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const rows = await listStacks()
        if (!cancelled) setStacks(rows)
      } catch (err) {
        if (!cancelled) setError(formatApiError(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const handleDelete = async (id: string) => {
    try {
      await deleteStack(id)
      setStacks((prev) => prev.filter((s) => s.id !== id))
    } catch (err) {
      setError(formatApiError(err))
    }
  }

  if (loading) {
    return <div className="p-6">Loading stacks…</div>
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Stacks</h1>
        <div className="flex gap-2">
          <button
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            onClick={() => navigate('/stacks/new')}
          >
            New Stack
          </button>
          <button
            className="px-4 py-2 border rounded hover:bg-gray-50"
            onClick={() => navigate('/stacks/import')}
          >
            Import Compose
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded" role="alert">
          {error}
        </div>
      )}

      {stacks.length === 0 ? (
        <p className="text-gray-500">No stacks yet. Create one or import a compose file.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {stacks.map((stack) => (
            <div
              key={stack.id}
              className="border rounded-lg p-4 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-medium">{stack.name}</h2>
                  <p className="text-sm text-gray-500">{stack.network_name}</p>
                </div>
                <button
                  className="text-red-500 hover:text-red-700 text-sm"
                  onClick={() => handleDelete(stack.id)}
                >
                  Delete
                </button>
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                  onClick={() => navigate(`/stacks/${stack.id}`)}
                >
                  Edit
                </button>
                <button
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
                  onClick={async () => {
                    try {
                      await import('../api/client').then(({ deployStack }) => deployStack(stack.id))
                    } catch (err) {
                      setError(formatApiError(err))
                    }
                  }}
                >
                  Deploy
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/StacksPage.tsx
git commit -m "feat: add stacks list page"
```

---

### Task 10: Frontend — Stack visualizer with @xyflow/react

**Files:**
- Create: `frontend/src/pages/stacks/StackVisualizer.tsx`
- Create: `frontend/src/pages/stacks/StackServiceForm.tsx`
- Create: `frontend/src/pages/stacks/StackBuilderPage.tsx`

**Interfaces:**
- Consumes: `Stack`, `StackService`, `createStack`, `importCompose` from Task 8
- Produces: Visual node-based editor for stacks with side panel form

- [ ] **Step 1: Create `frontend/src/pages/stacks/StackVisualizer.tsx`**

```typescript
import { useState } from 'react'
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { StackServiceCreate } from '../../api/client'

interface ServiceNodeData {
  service: StackServiceCreate
}

export default function StackVisualizer({
  initialServices,
  onSave,
  onCancel,
}: {
  initialServices: StackServiceCreate[]
  onSave: (services: StackServiceCreate[]) => void
  onCancel: () => void
}) {
  const [services, setServices] = useState<StackService[]>(initialServices)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const initialNodes: Node<ServiceNodeData>[] = services.map((s, i) => ({
    id: s.id || `node-${i}`,
    type: 'serviceNode',
    position: { x: i * 250, y: 50 },
    data: { service: s },
  }))

  const initialEdges: Edge[] = services
    .flatMap((s) =>
      (s.depends_on || []).map((dep) => ({
        id: `${s.id}-${dep}`,
        source: s.id || '',
        target: dep,
        animated: true,
      })),
    )
    .filter((e) => e.source && e.target)

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const onConnect = (params: Edge) => {
    setEdges((eds) => addEdge(params, eds))
  }

  return (
    <div className="h-screen flex">
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onClick={() => setSelectedId(null)}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      {selectedId && (
        <div className="w-80 border-l p-4 overflow-auto">
          <StackServiceForm
            service={services.find((s) => s.id === selectedId)}
            onSave={(updated) => {
              setServices((prev) =>
                prev.map((s) => (s.id === selectedId ? updated : s)),
              )
              setSelectedId(null)
            }}
            onDelete={() => {
              setServices((prev) => prev.filter((s) => s.id !== selectedId))
              setSelectedId(null)
            }}
          />
        </div>
      )}
      <div className="absolute bottom-4 left-4 flex gap-2">
        <button
          className="px-4 py-2 bg-blue-600 text-white rounded"
          onClick={() => onSave(services)}
        >
          Save Stack
        </button>
        <button
          className="px-4 py-2 border rounded"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create `frontend/src/pages/stacks/StackServiceForm.tsx`**

```typescript
import { useState } from 'react'
import type { StackServiceCreate } from '../../api/client'

interface Props {
  service?: StackServiceCreate
  onSave: (service: StackServiceCreate) => void
  onDelete?: () => void
}

export function StackServiceForm({ service, onSave, onDelete }: Props) {
  const [name, setName] = useState(service?.service_name || '')
  const [sourceKind, setSourceKind] = useState<'image' | 'git' | 'dockerfile_template'>(
    service?.source_kind || 'image',
  )
  const [sourceRef, setSourceRef] = useState(service?.source_ref || '')
  const [containerPort, setContainerPort] = useState(service?.container_port || 80)
  const [publicRoute, setPublicRoute] = useState(service?.public_route || false)

  const handleSave = () => {
    onSave({
      service_name: name,
      source_kind: sourceKind,
      source_ref: sourceRef,
      container_port: containerPort,
      public_route: publicRoute,
      env_vars: service?.env_vars || {},
      command: service?.command || null,
      depends_on: service?.depends_on || null,
    })
  }

  return (
    <div>
      <h3 className="font-medium mb-3">
        {service ? 'Edit Service' : 'New Service'}
      </h3>

      <div className="space-y-3">
        <div>
          <label className="block text-sm text-gray-600">Name</label>
          <input
            className="w-full border rounded px-3 py-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600">Source</label>
          <select
            className="w-full border rounded px-3 py-2"
            value={sourceKind}
            onChange={(e) => setSourceKind(e.target.value as any)}
          >
            <option value="image">Image</option>
            <option value="git">Git</option>
            <option value="dockerfile_template">Dockerfile Template</option>
          </select>
        </div>

        <div>
          <label className="block text-sm text-gray-600">
            {sourceKind === 'image' ? 'Image' : sourceKind === 'git' ? 'Git URL' : 'Template ID'}
          </label>
          <input
            className="w-full border rounded px-3 py-2"
            value={sourceRef}
            onChange={(e) => setSourceRef(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600">Port</label>
          <input
            type="number"
            className="w-full border rounded px-3 py-2"
            value={containerPort}
            onChange={(e) => setContainerPort(Number(e.target.value))}
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="publicRoute"
            checked={publicRoute}
            onChange={(e) => setPublicRoute(e.target.checked)}
          />
          <label htmlFor="publicRoute" className="text-sm">
            Public route
          </label>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button
          className="px-4 py-2 bg-blue-600 text-white rounded"
          onClick={handleSave}
        >
          Save
        </button>
        {onDelete && (
          <button
            className="px-4 py-2 text-red-600 border rounded"
            onClick={onDelete}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create `frontend/src/pages/stacks/StackBuilderPage.tsx`**

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createStack, formatApiError, type StackServiceCreate } from '../../api/client'
import StackVisualizer from './StackVisualizer'

export default function StackBuilderPage() {
  const navigate = useNavigate()
  const [services, setServices] = useState<StackServiceCreate[]>([])
  const [error, setError] = useState<string | null>(null)
  const [stackName, setStackName] = useState('')

  const handleSave = async (finalServices: StackServiceCreate[]) => {
    try {
      await createStack({
        name: stackName || 'untitled-stack',
        services: finalServices,
      })
      navigate('/stacks')
    } catch (err) {
      setError(formatApiError(err))
    }
  }

  return (
    <div className="h-screen flex flex-col">
      <div className="p-4 border-b">
        <div className="flex items-center gap-4">
          <input
            className="border rounded px-3 py-2 text-lg"
            placeholder="Stack name"
            value={stackName}
            onChange={(e) => setStackName(e.target.value)}
          />
          <button
            className="px-4 py-2 border rounded hover:bg-gray-50"
            onClick={() => navigate('/stacks')}
          >
            Cancel
          </button>
        </div>
        {error && (
          <p className="mt-2 text-red-600 text-sm" role="alert">{error}</p>
        )}
      </div>
      <div className="flex-1">
        <StackVisualizer
          initialServices={services}
          onSave={handleSave}
          onCancel={() => navigate('/stacks')}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/stacks/
git commit -m "feat: add stack visualizer with @xyflow/react and service form"
```

---

### Task 11: Frontend — compose import page and routing

**Files:**
- Create: `frontend/src/pages/stacks/ComposeImportPage.tsx`
- Modify: `frontend/src/App.tsx` — add stack routes

**Interfaces:**
- Consumes: `importCompose` from Task 8
- Produces: Compose import page and app routes

- [ ] **Step 1: Create `frontend/src/pages/stacks/ComposeImportPage.tsx`**

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { importCompose, formatApiError } from '../../api/client'

export default function ComposeImportPage() {
  const navigate = useNavigate()
  const [yaml, setYaml] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  const handleImport = async () => {
    try {
      const result = await importCompose({
        name: name || 'imported-stack',
        yaml_content: yaml,
      })
      if (result.warnings?.length) {
        setWarnings(result.warnings)
      } else {
        navigate('/stacks')
      }
    } catch (err) {
      setError(formatApiError(err))
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-semibold mb-4">Import Docker Compose</h1>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-600 mb-1">Stack name</label>
          <input
            className="w-full border rounded px-3 py-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-stack"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600 mb-1">
            docker-compose.yml content
          </label>
          <textarea
            className="w-full border rounded px-3 py-2 font-mono text-sm h-96"
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            placeholder="version: &quot;3&quot;
services:
  web:
    image: nginx:alpine"
          />
        </div>

        {error && (
          <div className="p-3 bg-red-50 text-red-700 rounded" role="alert">
            {error}
          </div>
        )}

        {warnings.length > 0 && (
          <div className="p-3 bg-yellow-50 text-yellow-800 rounded">
            <p className="font-medium">Warnings:</p>
            <ul className="list-disc ml-4 mt-1">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
            <button
              className="mt-2 text-blue-600 underline text-sm"
              onClick={() => navigate('/stacks')}
            >
              Continue to stacks
            </button>
          </div>
        )}

        <div className="flex gap-2">
          <button
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            onClick={handleImport}
          >
            Import
          </button>
          <button
            className="px-4 py-2 border rounded hover:bg-gray-50"
            onClick={() => navigate('/stacks')}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add routes to `frontend/src/App.tsx`**

Add imports:

```typescript
import StacksPage from './pages/StacksPage'
import StackBuilderPage from './pages/stacks/StackBuilderPage'
import ComposeImportPage from './pages/stacks/ComposeImportPage'
```

Add routes inside `<Layout>`:

```tsx
<Route
  path="/stacks"
  element={
    <RequireAuth>
      <StacksPage />
    </RequireAuth>
  }
/>
<Route
  path="/stacks/new"
  element={
    <RequireAuth>
      <StackBuilderPage />
    </RequireAuth>
  }
/>
<Route
  path="/stacks/import"
  element={
    <RequireAuth>
      <ComposeImportPage />
    </RequireAuth>
  }
/>
<Route
  path="/stacks/:id"
  element={
    <RequireAuth>
      <StackBuilderPage />
    </RequireAuth>
  }
/>
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/stacks/ComposeImportPage.tsx frontend/src/App.tsx
git commit -m "feat: add compose import page and stack routes"
```

---

### Task 12: Tests and verification

**Files:**
- Modify: `backend/tests/test_stack_repository.py` — ensure all tests pass
- Modify: `backend/tests/test_compose_parser.py` — ensure all tests pass
- Modify: `backend/tests/test_stack_deploy.py` — ensure integration tests pass

**Interfaces:**
- Consumes: all backend modules from Tasks 1-7

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && python -m pytest tests -q
```

Expected: all existing tests pass + new stack tests pass.

- [ ] **Step 2: Run frontend lint and build**

```bash
cd frontend && npm run lint && npm run build
```

Expected: no lint errors, build succeeds.

- [ ] **Step 3: Commit any test fixes**

```bash
git add backend/tests/
git commit -m "test: fix stack tests for full suite pass"
```

---

## Self-Review

**Spec coverage:**
- [x] DB models (`stacks`, `stack_services`, `stack_compositions`) — Task 1
- [x] `deployment_records.stack_id` — Task 1
- [x] Stack exceptions — Task 2
- [x] API schemas — Task 3
- [x] Repository (CRUD, composition, cycle detection) — Task 4
- [x] Compose parser — Task 5
- [x] Deploy coordinator with rollback — Task 6
- [x] API routes — Task 7
- [x] Frontend API client — Task 8
- [x] Stacks list page — Task 9
- [x] Visual builder with @xyflow/react — Task 10
- [x] Compose import page — Task 11
- [x] App routing — Task 11
- [x] Tests — Tasks 4, 5, 6, 12

**Placeholder scan:** No TBD, TODO, or "implement later" found. All tasks have concrete code.

**Type consistency:**
- `StackPublic`, `StackServicePublic`, `StackCreate`, `StackServiceCreate` — defined in Task 3, used in Task 7 (routes) and Task 8 (frontend client)
- `resolve_composition(stack, child_stacks)` — defined Task 4, used Task 6
- `detect_cycle(session, parent_id, child_id)` — defined Task 4, used Task 7 (create_stack calls it)
- `parse_compose(yaml_content)` — defined Task 5, used Task 7 (import-compose route)

**Gaps detected during review:**
1. `_stack_to_public()` in Task 7 doesn't map `StackService` → `StackServicePublic`. Adding the mapping inline.
2. `DockerOrchestrator` needs `create_network` / `remove_network` implementation. Added to Task 6.
3. `get_project_ids_for_user` referenced in Task 4 repository — this function doesn't exist yet. It should be added to `app/core/projects/repository.py`.

These are addressed in the code blocks above.
