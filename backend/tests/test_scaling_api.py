"""API tests for scaling policy read/write and RPS signal status."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import scaling
from app.core.monitoring.edge_requests import EdgeRequestRates
from app.core.traffic.traffic_router import NoopTrafficRouter

CONTAINER_NAME = "vela-test"
POLICY_URL = f"/api/scaling/policies/{CONTAINER_NAME}"

CPU_POLICY = {
    "enabled": True,
    "min_replicas": 1,
    "max_replicas": 3,
    "metric": "cpu_percent",
    "scale_up_threshold": 70.0,
    "scale_down_threshold": 30.0,
    "cooldown_seconds": 60,
    "scale_up_stabilization_seconds": 120,
    "scale_down_stabilization_seconds": 120,
}

RPS_POLICY = {
    **CPU_POLICY,
    "metric": "requests_per_second",
    "scale_up_threshold": 100.0,
    "scale_down_threshold": 10.0,
}


class _EdgeRouter:
    async def get_route(self, route_id: str) -> object:
        return SimpleNamespace(host="web.example")


@pytest.fixture(autouse=True)
def _default_noop_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scaling, "get_traffic_router", lambda: NoopTrafficRouter())


def test_put_creates_policy_and_get_one_returns_it(api_client: TestClient) -> None:
    created = api_client.put(POLICY_URL, json=CPU_POLICY)
    assert created.status_code == 200
    data = created.json()
    assert data["container_name"] == CONTAINER_NAME
    assert data["metric"] == "cpu_percent"
    assert data["min_replicas"] == 1
    assert data["max_replicas"] == 3
    assert data["signal_unavailable"] is False

    fetched = api_client.get(POLICY_URL)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == data["id"]


def test_get_one_missing_policy_returns_404(api_client: TestClient) -> None:
    assert api_client.get(POLICY_URL).status_code == 404


def test_get_list_returns_accessible_policies(api_client: TestClient) -> None:
    assert api_client.get("/api/scaling/policies").json() == []

    api_client.put(POLICY_URL, json=CPU_POLICY)
    data = api_client.get("/api/scaling/policies").json()
    assert [row["container_name"] for row in data] == [CONTAINER_NAME]


def test_put_updates_existing_policy(api_client: TestClient) -> None:
    first = api_client.put(POLICY_URL, json=CPU_POLICY).json()
    updated = api_client.put(
        POLICY_URL, json={**CPU_POLICY, "max_replicas": 5}
    ).json()
    assert updated["id"] == first["id"]
    assert updated["max_replicas"] == 5
    assert api_client.get(POLICY_URL).json()["max_replicas"] == 5


def test_rps_policy_marks_signal_unavailable(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(scaling, "get_traffic_router", lambda: _EdgeRouter())
    monkeypatch.setattr(
        scaling,
        "get_edge_request_rates",
        lambda: EdgeRequestRates({}, False),
    )

    created = api_client.put(POLICY_URL, json=RPS_POLICY)
    assert created.status_code == 200
    assert created.json()["signal_unavailable"] is True
    assert api_client.get(POLICY_URL).json()["signal_unavailable"] is True
    assert api_client.get("/api/scaling/policies").json()[0]["signal_unavailable"] is True


def test_rps_policy_signal_available(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(scaling, "get_traffic_router", lambda: _EdgeRouter())
    monkeypatch.setattr(
        scaling,
        "get_edge_request_rates",
        lambda: EdgeRequestRates({"web.example": 2.0}, True),
    )

    created = api_client.put(POLICY_URL, json=RPS_POLICY)
    assert created.json()["signal_unavailable"] is False


def test_noop_router_keeps_rps_signal_unavailable_false(
    api_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        scaling,
        "get_edge_request_rates",
        lambda: EdgeRequestRates({}, False),
    )

    created = api_client.put(POLICY_URL, json=RPS_POLICY)
    assert created.json()["signal_unavailable"] is False


def test_cpu_policy_ignores_edge_signal_status(
    api_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(scaling, "get_traffic_router", lambda: _EdgeRouter())
    monkeypatch.setattr(
        scaling,
        "get_edge_request_rates",
        lambda: EdgeRequestRates({}, False),
    )

    created = api_client.put(POLICY_URL, json=CPU_POLICY)
    assert created.json()["signal_unavailable"] is False
