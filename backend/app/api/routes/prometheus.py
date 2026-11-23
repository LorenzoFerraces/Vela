from __future__ import annotations

import os
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_orchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.enums import ContainerStatus
from app.core.exceptions import NotAuthenticatedError
from app.core.monitoring.edge_requests import get_edge_request_rates
from app.db.models import ContainerMetric, DeployJobRecord

router = APIRouter()

# metric name -> (HELP text, sample lines)
Families = dict[str, tuple[str, list[str]]]


def require_metrics_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("VELA_METRICS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Metrics scraping is not configured")
    provided = authorization.removeprefix("Bearer ") if authorization else ""
    if not secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise NotAuthenticatedError("Invalid metrics token")


def _escape_label_value(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _add(
    families: Families,
    name: str,
    help_text: str,
    value: float,
    labels: dict[str, str] | None = None,
) -> None:
    sample = f"{name} {value}"
    if labels:
        rendered = ",".join(
            f'{key}="{_escape_label_value(text)}"' for key, text in labels.items()
        )
        sample = f"{name}{{{rendered}}} {value}"
    families.setdefault(name, (help_text, []))[1].append(sample)


@router.get("/metrics", dependencies=[Depends(require_metrics_token)])
async def prometheus_metrics(
    session: AsyncSession = Depends(get_db),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    families: Families = {}
    _add(families, "vela_api_up", "API is serving requests", 1)
    edge = get_edge_request_rates()
    _add(families, "vela_edge_signal_available", "Edge request signal is available", 1 if edge.available else 0)
    for host, rate in sorted(edge.rates_by_host.items()):
        _add(families, "vela_edge_requests_per_second", "Requests per second at the edge", rate, {"host": host})

    newest = (await session.execute(
        select(func.max(ContainerMetric.timestamp))
    )).scalar_one_or_none()
    if newest is None:
        collector_age_seconds = 0.0
    else:
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        collector_age_seconds = max(0.0, (datetime.now(timezone.utc) - newest).total_seconds())
    _add(
        families,
        "vela_collector_last_sample_age_seconds",
        "Seconds since the newest stored container metric sample (0 when none exist)",
        collector_age_seconds,
    )

    containers = await orchestrator.list()
    states = Counter(str(info.status) for info in containers)
    for container_status in ContainerStatus:
        _add(
            families,
            "vela_workloads_by_state",
            "Workloads by state",
            states.get(container_status.value, 0),
            {"state": container_status.value},
        )

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = (await session.execute(
        select(DeployJobRecord.status, func.count())
        .where(
            DeployJobRecord.finished_at >= since,
            DeployJobRecord.status.in_(("succeeded", "failed")),
        )
        .group_by(DeployJobRecord.status)
    )).all()
    counts = {row[0]: row[1] for row in rows}
    succeeded = counts.get("succeeded", 0)
    failed = counts.get("failed", 0)
    total = succeeded + failed
    rate = succeeded / total if total else 0.0
    _add(
        families,
        "vela_deploy_success_rate",
        "Fraction of terminal deploy jobs that succeeded in the last 24h",
        rate,
    )

    lines: list[str] = []
    for name, (help_text, samples) in families.items():
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
        lines += samples
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
