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

from app.api.deps import get_current_user, get_db
from app.db.models import ContainerLog, LogLevel, LogSource, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])


@router.get("/")
async def query_logs(
    session: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)] = ...,
    container_id: str | None = Query(None),
    container_name: str | None = Query(None),
    level: str | None = Query(None),
    source: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    q: str | None = Query(None, description="Full-text search"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    conditions: list[sa.ColumnElement] = []

    if container_id:
        conditions.append(ContainerLog.container_id == container_id)
    if container_name:
        conditions.append(ContainerLog.container_name == container_name)
    if level:
        conditions.append(ContainerLog.level == LogLevel(level))
    if source:
        conditions.append(ContainerLog.source == LogSource(source))
    if start_time:
        conditions.append(ContainerLog.timestamp >= start_time)
    if end_time:
        conditions.append(ContainerLog.timestamp <= end_time)
    if q:
        _escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(ContainerLog.message.like(f"%{_escaped}%", escape="\\"))

    count_query = sa.select(sa.func.count()).select_from(ContainerLog)
    if conditions:
        count_query = count_query.where(sa.and_(*conditions))
    total = (await session.execute(count_query)).scalar() or 0

    entries_query = sa.select(ContainerLog).order_by(
        ContainerLog.timestamp.desc()
    )
    if conditions:
        entries_query = entries_query.where(sa.and_(*conditions))
    entries_query = entries_query.limit(limit).offset(offset)
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
    _current_user: Annotated[User, Depends(get_current_user)] = ...,
    container_id: str | None = Query(None),
    level: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    limit: int = Query(5000, ge=1, le=50000),
) -> StreamingResponse:
    conditions: list[sa.ColumnElement] = []
    if container_id:
        conditions.append(ContainerLog.container_id == container_id)
    if level:
        conditions.append(ContainerLog.level == LogLevel(level))
    if start_time:
        conditions.append(ContainerLog.timestamp >= start_time)
    if end_time:
        conditions.append(ContainerLog.timestamp <= end_time)

    query = sa.select(ContainerLog).order_by(ContainerLog.timestamp.desc()).limit(
        limit
    )
    if conditions:
        query = query.where(sa.and_(*conditions))

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
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "timestamp": row.timestamp.isoformat(),
                "container_id": row.container_id,
                "container_name": row.container_name or "",
                "source": row.source,
                "level": row.level,
                "message": row.message,
            }
        )

    return StreamingResponse(
        io.BytesIO(stream.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=container-logs.csv"},
    )
