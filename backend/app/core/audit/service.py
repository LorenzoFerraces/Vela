"""Audit log emission and query functions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

logger = logging.getLogger(__name__)


class AuditLogQueryResult(NamedTuple):
    entries: list[AuditLog]
    total: int


def _build_conditions(
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    target_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[sa.ColumnElement]:
    conditions: list[sa.ColumnElement] = []
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if action is not None:
        conditions.append(AuditLog.action == action)
    if target_type is not None:
        conditions.append(AuditLog.target_type == target_type)
    if from_date is not None:
        conditions.append(AuditLog.created_at >= from_date)
    if to_date is not None:
        conditions.append(AuditLog.created_at <= to_date)
    return conditions


async def emit_audit_log(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    """Append a single audit log entry. Flushes only; the caller's commit persists it.

    Best effort: if the flush fails the entry is dropped and the error logged;
    the savepoint keeps the caller's transaction usable.
    """
    try:
        async with session.begin_nested():
            entry = AuditLog(
                user_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
            session.add(entry)
            await session.flush()
    except Exception:
        logger.exception(
            "Failed to emit audit log; entry dropped: action=%s target=%s",
            action,
            target_id,
        )


async def list_audit_logs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    target_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AuditLogQueryResult:
    """Query audit logs with optional filters, ordered newest first. Returns entries and total count."""
    conditions = _build_conditions(user_id, action, target_type, from_date, to_date)

    if conditions:
        total = (await session.execute(
            sa.select(sa.func.count()).select_from(AuditLog).where(sa.and_(*conditions))
        )).scalar() or 0
    else:
        total = (await session.execute(
            sa.select(sa.func.count()).select_from(AuditLog)
        )).scalar() or 0

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if conditions:
        stmt = stmt.where(sa.and_(*conditions))
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return AuditLogQueryResult(entries=list(result.scalars().all()), total=total)
