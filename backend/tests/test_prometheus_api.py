import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.routes.prometheus import require_metrics_token
from app.core.enums import ContainerStatus
from app.core.monitoring.edge_requests import reset_edge_request_cache
from app.db.models import ContainerMetric, DeployJobRecord


def test_metrics_requires_configured_token(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    app = api_client.app
    response = TestClient(app).get("/metrics")
    assert response.status_code == 401


def test_metrics_reports_platform_and_project_signals(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    response = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "vela_api_up 1" in body
    assert "vela_workloads_by_state" in body
    assert "# TYPE vela_deploy_success_rate gauge" in body
    type_lines = [line for line in body.splitlines() if line.startswith("# TYPE ")]
    assert type_lines
    for line in type_lines:
        assert body.splitlines().count(line) == 1, f"duplicate metric family: {line}"
    for container_status in ContainerStatus:
        assert f'state="{container_status.value}"' in body


def test_metrics_disabled_without_token(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "")
    assert TestClient(api_client.app).get("/metrics").status_code == 503


def test_metrics_deploy_success_rate_uses_terminal_jobs(
    api_client, monkeypatch, db_session_factory
) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    now = datetime.now(UTC)

    async def seed() -> None:
        async with db_session_factory() as session:
            for index, job_status in enumerate(("succeeded", "succeeded", "failed")):
                session.add(DeployJobRecord(
                    job_id=f"job-{index}",
                    kind="deploy",
                    project_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    name=f"app-{index}",
                    status=job_status,
                    finished_at=now,
                ))
            await session.commit()

    asyncio.run(seed())
    body = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    ).text
    rate_line = next(
        line for line in body.splitlines()
        if line.startswith("vela_deploy_success_rate ")
    )
    assert abs(float(rate_line.split()[1]) - 2 / 3) < 1e-6


def test_metrics_success_rate_counts_outcomes_older_than_poller_ttl(
    api_client, monkeypatch, db_session_factory, deploy_jobs
) -> None:
    """A job aged past the 300s API window still counts toward the 24h rate."""
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    project_id = uuid.uuid4()

    async def seed_and_sweep() -> None:
        async with db_session_factory() as session:
            session.add(DeployJobRecord(
                job_id="old-but-retained",
                kind="deploy",
                project_id=project_id,
                user_id=uuid.uuid4(),
                name="app-old",
                status="succeeded",
                finished_at=datetime.now(UTC) - timedelta(minutes=10),
            ))
            await session.commit()
        # active() runs the sweep; it must not erase metric outcomes.
        assert await deploy_jobs.active(project_ids={project_id}) == []

    asyncio.run(seed_and_sweep())
    body = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    ).text
    rate_line = next(
        line for line in body.splitlines()
        if line.startswith("vela_deploy_success_rate ")
    )
    assert float(rate_line.split()[1]) == 1.0


def test_metrics_token_comparison_handles_non_ascii(monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "sécrêt-🔑")
    require_metrics_token("Bearer sécrêt-🔑")


def test_edge_host_label_values_are_escaped(api_client, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    log = tmp_path / "access.log"
    log.write_text(json.dumps({
        "StartUTC": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "RequestHost": 'bad"host\\name\nnext',
    }) + "\n", encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    body = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    ).text
    assert 'host="bad\\"host\\\\name\\nnext"' in body


def test_metrics_reports_collector_sample_age_with_no_samples(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    body = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    ).text
    assert (
        "# HELP vela_collector_last_sample_age_seconds "
        "Seconds since the newest stored container metric sample (0 when none exist)"
    ) in body
    assert "# TYPE vela_collector_last_sample_age_seconds gauge" in body
    age_line = next(
        line for line in body.splitlines()
        if line.startswith("vela_collector_last_sample_age_seconds ")
    )
    assert float(age_line.split()[1]) == 0.0


def test_metrics_collector_age_reflects_stored_samples(
    api_client, monkeypatch, db_session_factory
) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(ContainerMetric(
                container_id="collected-container",
                timestamp=datetime.now(UTC) - timedelta(minutes=5),
                cpu_percent=1.0,
                memory_usage_bytes=1024,
                memory_limit_bytes=2048,
                memory_percent=50.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
            ))
            await session.commit()

    asyncio.run(seed())
    body = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    ).text
    age_line = next(
        line for line in body.splitlines()
        if line.startswith("vela_collector_last_sample_age_seconds ")
    )
    assert 295 <= float(age_line.split()[1]) <= 305
