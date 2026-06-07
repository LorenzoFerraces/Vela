"""Container health monitoring and alerting service.

Periodically checks container status and triggers alerts on state changes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications.alert_service import AlertService
from app.core.containers.docker_orchestrator import VELA_OWNER_LABEL
from app.core.notifications.email_provider import EmailProvider, get_email_provider
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import ProviderConnectionError
from app.core.containers.orchestrator import ContainerOrchestrator
from app.db.engine import get_session_factory
from app.db.models import DeploymentRecord, User

logger = logging.getLogger(__name__)

MONITOR_INTERVAL_SECONDS = int(
    os.environ.get("VELA_CONTAINER_MONITOR_INTERVAL_SECONDS", "15")
)
MONITOR_ENABLED = os.environ.get("VELA_CONTAINER_MONITOR_ENABLED", "1").strip() != "0"

_tracked_container_count = 0

# Statuses that count as "was up" before a stop/failure/disappearance.
_ACTIVE_CONTAINER_STATUSES = frozenset(
    {
        ContainerStatus.CREATED,
        ContainerStatus.RUNNING,
        ContainerStatus.RESTARTING,
        ContainerStatus.PAUSED,
    }
)


def get_tracked_container_count() -> int:
    """Number of Vela-owned containers seen on the last monitoring pass."""
    return _tracked_container_count


class ContainerStateSnapshot:
    """Tracks container state for change detection."""

    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {}

    def update(
        self,
        container_id: str,
        container_name: str,
        status: ContainerStatus,
        health: HealthStatus,
    ) -> None:
        """Record current state."""
        self.state[container_id] = {
            "name": container_name,
            "status": status,
            "health": health,
        }

    def get_state(self, container_id: str) -> dict[str, Any] | None:
        """Get last known state."""
        return self.state.get(container_id)

    def pop_state(self, container_id: str) -> dict[str, Any] | None:
        """Remove and return last known state."""
        return self.state.pop(container_id, None)

    def detect_change(
        self,
        container_id: str,
        status: ContainerStatus,
        health: HealthStatus,
    ) -> str | None:
        """
        Detect if container state changed.

        Returns event_type ('stop', 'failure', 'unhealthy') or None if no change.
        """
        previous = self.get_state(container_id)
        if previous is None:
            return None

        prev_status = ContainerStatus(previous["status"])
        prev_health = HealthStatus(previous["health"])

        if prev_status in _ACTIVE_CONTAINER_STATUSES:
            if status == ContainerStatus.DEAD:
                return "failure"
            if status == ContainerStatus.STOPPED:
                return "stop"

        if prev_health == HealthStatus.HEALTHY and health == HealthStatus.UNHEALTHY:
            return "unhealthy"

        return None

    def detect_disappeared(self, container_id: str) -> str | None:
        """
        Detect a container that was active but is no longer returned by Docker.

        Typical when the workload was removed (`docker rm`) instead of stopped.
        """
        previous = self.get_state(container_id)
        if previous is None:
            return None

        prev_status = ContainerStatus(previous["status"])
        if prev_status in _ACTIVE_CONTAINER_STATUSES:
            return "stop"
        return None


async def get_vela_containers(
    orchestrator: ContainerOrchestrator,
) -> dict[str, tuple[str, ContainerStatus, HealthStatus]]:
    """
    Get all Vela-managed containers with their status.

    Returns: {container_id: (container_name, status, health)}
    """
    global _tracked_container_count

    try:
        containers = await orchestrator.list()
        vela_containers: dict[str, tuple[str, ContainerStatus, HealthStatus]] = {}

        for container in containers:
            if VELA_OWNER_LABEL not in container.labels:
                continue

            vela_containers[container.id] = (
                container.name,
                container.status,
                container.health,
            )

        _tracked_container_count = len(vela_containers)
        return vela_containers
    except Exception as e:
        logger.exception("Failed to list containers: %s", e)
        return {}


async def get_container_owner(
    session: AsyncSession, container_id: str
) -> User | None:
    """Look up the user who owns a container via deployment record."""
    try:
        stmt = (
            select(DeploymentRecord)
            .where(DeploymentRecord.container_id == container_id)
            .order_by(DeploymentRecord.created_at.desc())
            .limit(1)
        )
        record = await session.scalar(stmt)
        if not record:
            return None

        stmt = select(User).where(User.id == record.user_id)
        user = await session.scalar(stmt)
        return user
    except Exception as e:
        logger.exception("Failed to get container owner: %s", e)
        return None


async def _send_alert_if_configured(
    *,
    email_provider: EmailProvider,
    session: AsyncSession,
    owner: User,
    container_id: str,
    container_name: str,
    event_type: str,
    details: str,
) -> None:
    alert_service = AlertService(email_provider, session)
    success = await alert_service.send_container_alert(
        user_id=owner.id,
        container_id=container_id,
        container_name=container_name,
        event_type=event_type,
        details=details,
    )
    if success:
        logger.info("Alert sent for %s: %s", container_name, event_type)
    else:
        logger.warning(
            "Alert not sent for %s (%s); check email prefs, dedup window, or Brevo config",
            container_name,
            event_type,
        )


async def monitor_containers_once(
    orchestrator: ContainerOrchestrator,
    email_provider: EmailProvider,
    session: AsyncSession,
    state: ContainerStateSnapshot,
) -> None:
    """Single monitoring pass: detect state changes and send alerts."""
    try:
        containers = await get_vela_containers(orchestrator)
        seen_ids = set(containers.keys())
        alerts_queued = 0

        for container_id, (container_name, status, health) in containers.items():
            event_type = state.detect_change(container_id, status, health)
            state.update(container_id, container_name, status, health)

            if not event_type:
                continue

            alerts_queued += 1
            owner = await get_container_owner(session, container_id)
            if not owner:
                logger.warning(
                    "Container %s (%s) changed to %s but has no deployment owner; skipping alert",
                    container_name,
                    container_id[:12],
                    event_type,
                )
                continue

            await _send_alert_if_configured(
                email_provider=email_provider,
                session=session,
                owner=owner,
                container_id=container_id,
                container_name=container_name,
                event_type=event_type,
                details=f"Container status: {status}, Health: {health}",
            )

        for container_id in list(state.state.keys()):
            if container_id in seen_ids:
                continue

            event_type = state.detect_disappeared(container_id)
            previous = state.pop_state(container_id)
            if not event_type or previous is None:
                continue

            container_name = str(previous.get("name") or container_id[:12])
            alerts_queued += 1
            owner = await get_container_owner(session, container_id)
            if not owner:
                logger.warning(
                    "Container %s disappeared but has no deployment owner; skipping alert",
                    container_name,
                )
                continue

            await _send_alert_if_configured(
                email_provider=email_provider,
                session=session,
                owner=owner,
                container_id=container_id,
                container_name=container_name,
                event_type=event_type,
                details="Container no longer listed by Docker (removed or unreachable)",
            )

        logger.debug(
            "Container monitor pass: tracked=%s alerts_queued=%s",
            len(seen_ids),
            alerts_queued,
        )

    except Exception as e:
        logger.exception("Error during monitoring pass: %s", e)


async def run_monitoring_loop() -> None:
    """
    Continuous monitoring loop that runs for the lifetime of the application.

    Polls container status every MONITOR_INTERVAL_SECONDS and sends alerts.
    """
    if not MONITOR_ENABLED:
        logger.info("Container monitoring is disabled")
        return

    logger.info(
        "Starting container monitoring (interval=%ss); "
        "state resets on API restart — wait one interval after deploy before stopping",
        MONITOR_INTERVAL_SECONDS,
    )

    from app.api.deps import get_orchestrator

    session_factory = get_session_factory()
    email_provider = get_email_provider(use_console=False)
    state = ContainerStateSnapshot()

    while True:
        try:
            orchestrator = get_orchestrator()
            async with session_factory() as session:
                await monitor_containers_once(
                    orchestrator, email_provider, session, state
                )
        except asyncio.CancelledError:
            logger.info("Container monitoring stopped")
            break
        except ProviderConnectionError:
            logger.debug("Docker unavailable; skipping container monitor pass")
        except Exception as e:
            logger.exception("Unexpected error in monitoring loop: %s", e)

        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
