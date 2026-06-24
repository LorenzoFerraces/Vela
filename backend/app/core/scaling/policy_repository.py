"""CRUD operations for ScalingPolicy rows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ScalingMetric
from app.core.models import ScalingPolicyConfig, ScalingPolicyInfo
from app.db.models import ScalingPolicy


class ScalingPolicyRuntime(BaseModel):
    """Policy plus engine state used by the scaling loop."""

    policy: ScalingPolicyInfo
    scale_up_condition_since: datetime | None
    scale_down_condition_since: datetime | None


def _orm_to_info(row: ScalingPolicy) -> ScalingPolicyInfo:
    return ScalingPolicyInfo(
        id=row.id,
        container_name=row.container_name,
        enabled=row.enabled,
        min_replicas=row.min_replicas,
        max_replicas=row.max_replicas,
        metric=ScalingMetric(row.metric),
        scale_up_threshold=row.scale_up_threshold,
        scale_down_threshold=row.scale_down_threshold,
        cooldown_seconds=row.cooldown_seconds,
        scale_up_stabilization_seconds=row.scale_up_stabilization_seconds,
        scale_down_stabilization_seconds=row.scale_down_stabilization_seconds,
        last_scaled_at=row.last_scaled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _orm_to_runtime(row: ScalingPolicy) -> ScalingPolicyRuntime:
    return ScalingPolicyRuntime(
        policy=_orm_to_info(row),
        scale_up_condition_since=row.scale_up_condition_since,
        scale_down_condition_since=row.scale_down_condition_since,
    )


async def get_policy(
    session: AsyncSession, container_name: str
) -> ScalingPolicyInfo | None:
    result = await session.execute(
        select(ScalingPolicy).where(ScalingPolicy.container_name == container_name)
    )
    row = result.scalar_one_or_none()
    return _orm_to_info(row) if row else None


async def upsert_policy(
    session: AsyncSession,
    container_name: str,
    config: ScalingPolicyConfig,
) -> ScalingPolicyInfo:
    result = await session.execute(
        select(ScalingPolicy).where(ScalingPolicy.container_name == container_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ScalingPolicy(
            id=uuid.uuid4(),
            container_name=container_name,
        )
        session.add(row)
    row.enabled = config.enabled
    row.min_replicas = config.min_replicas
    row.max_replicas = config.max_replicas
    row.metric = config.metric.value
    row.scale_up_threshold = config.scale_up_threshold
    row.scale_down_threshold = config.scale_down_threshold
    row.cooldown_seconds = config.cooldown_seconds
    row.scale_up_stabilization_seconds = config.scale_up_stabilization_seconds
    row.scale_down_stabilization_seconds = config.scale_down_stabilization_seconds
    row.scale_up_condition_since = None
    row.scale_down_condition_since = None
    await session.commit()
    await session.refresh(row)
    return _orm_to_info(row)


async def list_enabled_policies(session: AsyncSession) -> list[ScalingPolicyRuntime]:
    result = await session.execute(
        select(ScalingPolicy).where(ScalingPolicy.enabled.is_(True))
    )
    return [_orm_to_runtime(row) for row in result.scalars().all()]


async def update_stabilization_state(
    session: AsyncSession,
    container_name: str,
    *,
    scale_up_condition_since: datetime | None,
    scale_down_condition_since: datetime | None,
) -> None:
    result = await session.execute(
        select(ScalingPolicy).where(ScalingPolicy.container_name == container_name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    row.scale_up_condition_since = scale_up_condition_since
    row.scale_down_condition_since = scale_down_condition_since
    await session.commit()


async def record_scale_event(
    session: AsyncSession, container_name: str
) -> None:
    """Record a scale action and reset stabilization timers."""
    result = await session.execute(
        select(ScalingPolicy).where(ScalingPolicy.container_name == container_name)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        now = datetime.now(timezone.utc)
        row.last_scaled_at = now
        row.scale_up_condition_since = None
        row.scale_down_condition_since = None
        await session.commit()
