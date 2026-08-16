"""Container log query and export endpoints."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.projects.access import require_container_access
from app.db.models import ContainerLog, LogLevel, LogSource, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])


def _like_condition(q: str) -> sa.ColumnElement:
    # ponytail: LIKE search, not pg_trgm — sufficient for log lookup, avoids Postgres-only dependency
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return ContainerLog.message.like(f"%{escaped}%", escape="\\")


@router.get("/")
async def query_logs(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    container_id: str = Query(...),
    level: LogLevel | None = Query(None),
    source: LogSource | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    q: str | None = Query(None, description="Full-text search"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )

    conditions: list[sa.ColumnElement] = [
        ContainerLog.container_id == container_id
    ]
    if level is not None:
        conditions.append(ContainerLog.level == level)
    if source is not None:
        conditions.append(ContainerLog.source == source)
    if start_time:
        conditions.append(ContainerLog.timestamp >= start_time)
    if end_time:
        conditions.append(ContainerLog.timestamp <= end_time)
    if q:
        conditions.append(_like_condition(q))

    count_query = (
        sa.select(sa.func.count())
        .select_from(ContainerLog)
        .where(sa.and_(*conditions))
    )
    total = (await session.execute(count_query)).scalar() or 0

    entries_query = (
        sa.select(ContainerLog)
        .where(sa.and_(*conditions))
        .order_by(ContainerLog.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(entries_query)).scalars().all()

    return {
        "entries": [
            {
                "container_id": row.container_id,
                "container_name": row.container_name,
                "timestamp": row.timestamp.isoformat(),
                "source": row.source,
                "level": row.level,
                "message": row.message,
            }
            for row in rows
        ],
        "total": total,
    }


@router.get("/export")
async def export_logs(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    container_id: str = Query(...),
    level: LogLevel | None = Query(None),
    source: LogSource | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    q: str | None = Query(None, description="Full-text search"),
    limit: int = Query(5000, ge=1, le=50000),
) -> StreamingResponse:
    # ponytail: materializes up to `limit` rows in memory — accepted ceiling for CSV export
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )

    conditions: list[sa.ColumnElement] = [
        ContainerLog.container_id == container_id
    ]
    if level is not None:
        conditions.append(ContainerLog.level == level)
    if source is not None:
        conditions.append(ContainerLog.source == source)
    if start_time:
        conditions.append(ContainerLog.timestamp >= start_time)
    if end_time:
        conditions.append(ContainerLog.timestamp <= end_time)
    if q:
        conditions.append(_like_condition(q))

    query = (
        sa.select(ContainerLog)
        .where(sa.and_(*conditions))
        .order_by(ContainerLog.timestamp.desc())
        .limit(limit)
    )
    rows = (await session.execute(query)).scalars().all()

    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "timestamp",
            "container_id",
            "container_name",
            "source",
            "level",
            "message",
        ],
    )

    def _sanitize(value: str) -> str:
        if value and value[0] in ("=", "+", "-", "@"):
            return f"'{value}"
        return value

    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "timestamp": row.timestamp.isoformat(),
                "container_id": _sanitize(row.container_id),
                "container_name": _sanitize(row.container_name or ""),
                "source": row.source,
                "level": row.level,
                "message": _sanitize(row.message),
            }
        )

    return StreamingResponse(
        io.BytesIO(stream.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=container-logs.csv"},
    )
