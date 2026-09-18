"""Audit log read API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import AuditLogEntry, AuditLogListResponse
from app.core.audit.service import list_audit_logs
from app.db.models import User

router = APIRouter()


@router.get("/log", response_model=AuditLogListResponse)
async def get_audit_log(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    action: Annotated[str | None, Query(description="Filter by action")] = None,
    target_type: Annotated[str | None, Query(description="Filter by target type")] = None,
    from_date: Annotated[datetime | None, Query(description="Filter from date (ISO 8601)")] = None,
    to_date: Annotated[datetime | None, Query(description="Filter to date (ISO 8601)")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Max entries to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
) -> AuditLogListResponse:
    result = await list_audit_logs(
        session,
        user_id=current_user.id,
        action=action,
        target_type=target_type,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    return AuditLogListResponse(
        entries=[AuditLogEntry.model_validate(entry) for entry in result.entries],
        total=result.total,
    )
