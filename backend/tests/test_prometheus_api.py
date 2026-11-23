from fastapi.testclient import TestClient


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


def test_metrics_disabled_without_token(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "")
    assert TestClient(api_client.app).get("/metrics").status_code == 503
