"""Stack CRUD, composition resolution, and cycle detection."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    DuplicateStackNameError,
    StackCompositionCycleError,
    StackNotFoundError,
)
from app.core.projects.repository import list_project_ids_for_user, require_membership
from app.db.models import Stack, StackComposition, StackService


async def create_stack(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    services: list[StackService],
    child_stack_ids: list[uuid.UUID],
) -> Stack:
    """Create a stack with services and optional child stack references."""
    stack = Stack(
        project_id=project_id,
        name=name,
        network_name=f"vela-stack-{hashlib.sha256(name.encode()).hexdigest()[:12]}",
        services=services,
    )
    session.add(stack)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateStackNameError(name) from exc

    for child_id in child_stack_ids:
        cycle = await detect_cycle(session, stack.id, child_id)
        if cycle:
            raise StackCompositionCycleError(cycle)
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

    await require_membership(session, project_id=stack.project_id, user_id=user_id)
    return stack


async def list_stacks(session: AsyncSession, user_id: uuid.UUID) -> list[Stack]:
    """List all stacks belonging to projects the user is a member of."""
    project_ids = await list_project_ids_for_user(session, user_id)
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


async def update_stack(
    session: AsyncSession,
    stack_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    services: list[StackService],
    child_stack_ids: list[uuid.UUID] | None = None,
) -> Stack:
    """Update a stack's name, services, and composition. User must have write access."""
    stack = await get_stack(session, stack_id, user_id)
    if stack is None:
        raise StackNotFoundError(str(stack_id))

    from app.core.projects.enums import can_write

    membership = await require_membership(session, project_id=stack.project_id, user_id=user_id)
    if not can_write(membership.role):
        from app.core.exceptions import ProjectAccessDeniedError

        raise ProjectAccessDeniedError("You do not have permission to update this stack.")

    stack.name = name
    stack.network_name = f"vela-stack-{hashlib.sha256(name.encode()).hexdigest()[:12]}"

    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateStackNameError(name) from exc

    stack.services.clear()
    await session.flush()

    stack.services = services

    if child_stack_ids is not None:
        for child_id in child_stack_ids:
            cycle = await detect_cycle(session, stack.id, child_id)
            if cycle:
                raise StackCompositionCycleError(cycle)

        stack.compositions_parent.clear()
        await session.flush()

        for child_id in child_stack_ids:
            stack.compositions_parent.append(StackComposition(
                parent_stack_id=stack.id,
                child_stack_id=child_id,
            ))

    await session.flush()
    return stack


async def delete_stack(
    session: AsyncSession,
    stack_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete a stack. User must have write access to the stack's project."""
    stack = await get_stack(session, stack_id, user_id)
    if stack is None:
        raise StackNotFoundError(str(stack_id))

    from app.core.projects.enums import can_write

    membership = await require_membership(session, project_id=stack.project_id, user_id=user_id)
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
    Duplicate service names across stacks are disambiguated with a stack index prefix.
    """
    all_services: list[StackService] = []
    for child in child_stacks:
        all_services.extend(child.services)
    all_services.extend(stack.services)

    seen: dict[str, int] = {}
    for service in all_services:
        seen[service.service_name] = seen.get(service.service_name, 0) + 1

    dupes = {name for name, count in seen.items() if count > 1}

    keyed_services: list[tuple[str, StackService]] = []
    for child in child_stacks:
        for service in child.services:
            key = f"{child.name}/{service.service_name}" if service.service_name in dupes else service.service_name
            keyed_services.append((key, service))
    for service in stack.services:
        key = f"{stack.name}/{service.service_name}" if service.service_name in dupes else service.service_name
        keyed_services.append((key, service))

    name_to_service = {key: svc for key, svc in keyed_services}
    graph: dict[str, set[str]] = {key: set() for key, _ in keyed_services}

    for key, service in keyed_services:
        if service.depends_on:
            for dep in service.depends_on:
                if dep in graph:
                    graph[dep].add(key)
                elif dep in dupes:
                    for other_key, _ in keyed_services:
                        if other_key.endswith(f"/{dep}") and other_key != key:
                            graph[other_key].add(key)

    in_degree = {key: 0 for key in graph}
    for node, deps in graph.items():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue = [key for key, deg in in_degree.items() if deg == 0]
    sorted_keys: list[str] = []

    while queue:
        queue.sort()
        current = queue.pop(0)
        sorted_keys.append(current)
        for neighbor in graph.get(current, set()):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return [name_to_service[key] for key in sorted_keys if key in name_to_service]


async def detect_cycle(
    session: AsyncSession,
    parent_id: uuid.UUID,
    child_id: uuid.UUID,
) -> list[str] | None:
    """Check if adding parent → child composition would create a cycle.

    Traverses downward from child through its descendants to see if parent
    is reachable (which would form a cycle).

    Returns list of stack names forming the cycle, or None if no cycle.
    """
    if parent_id == child_id:
        stmt = select(Stack.name).where(Stack.id == parent_id)
        result = await session.execute(stmt)
        name = result.scalar_one_or_none()
        return [name] if name else ["unknown"]

    visited: set[uuid.UUID] = set()
    queue: list[uuid.UUID] = [child_id]
    path: dict[uuid.UUID, uuid.UUID | None] = {child_id: None}

    while queue:
        current = queue.pop(0)
        if current == parent_id:
            cycle_names = []
            node: uuid.UUID | None = current
            while node is not None:
                name_stmt = select(Stack.name).where(Stack.id == node)
                result = await session.execute(name_stmt)
                cycle_names.append(result.scalar_one_or_none() or "unknown")
                node = path.get(node)
            return list(reversed(cycle_names))

        visited.add(current)

        stmt = (
            select(StackComposition.child_stack_id)
            .where(StackComposition.parent_stack_id == current)
        )
        result = await session.execute(stmt)
        for row in result.mappings():
            next_id = row["child_stack_id"]
            if next_id not in visited:
                path[next_id] = current
                queue.append(next_id)

    return None
