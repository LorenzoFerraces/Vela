from __future__ import annotations

import os
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_orchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import NotAuthenticatedError
from app.core.monitoring.edge_requests import get_edge_request_rates
from app.db.models import DeploymentRecord

router = APIRouter()


def require_metrics_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("VELA_METRICS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Metrics scraping is not configured")
    provided = authorization.removeprefix("Bearer ") if authorization else ""
    if not secrets.compare_digest(provided, expected):
        raise NotAuthenticatedError("Invalid metrics token")


def _gauge(name: str, help_text: str, value: float, labels: dict[str, str] | None = None) -> list[str]:
    suffix = ""
    if labels:
        rendered = ",".join(f'{key}="{text}"' for key, text in labels.items())
        suffix = "{" + rendered + "}"
    return [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name}{suffix} {value}"]


@router.get("/metrics", dependencies=[Depends(require_metrics_token)])
async def prometheus_metrics(
    session: AsyncSession = Depends(get_db),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    lines: list[str] = []
    lines += _gauge("vela_api_up", "API is serving requests", 1)
    edge = get_edge_request_rates()
    lines += _gauge("vela_edge_signal_available", "Edge request signal is available", 1 if edge.available else 0)
    for host, rate in sorted(edge.rates_by_host.items()):
        lines += _gauge("vela_edge_requests_per_second", "Requests per second at the edge", rate, {"host": host})

    containers = await orchestrator.list()
    states = Counter(str(info.status) for info in containers)
    for state in ("running", "stopped", "failed"):
        lines += _gauge("vela_workloads_by_state", "Workloads by state", states.get(state, 0), {"state": state})

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total = (await session.execute(
        select(DeploymentRecord).where(DeploymentRecord.created_at >= since)
    )).scalars().all()
    succeeded = sum(1 for record in total if record.container_id is not None)
    rate = succeeded / len(total) if total else 0.0
    lines += _gauge("vela_deploy_success_rate", "Fraction of recent deploys that produced a container", rate)
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
