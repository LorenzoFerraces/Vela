"""App-level middleware tests (GZip response compression, security headers)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from tests.conftest import make_container_info


def test_large_json_response_is_gzipped(
    make_authed_client, test_user_id: uuid.UUID
) -> None:
    """A JSON body over the 500-byte minimum_size is gzip-encoded for gzip clients."""
    orchestrator = FakeContainerOrchestrator()
    for index in range(5):
        orchestrator.seed_container(
            make_container_info(owner_id=test_user_id, id=f"cid-gzip-{index}")
        )
    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get("/api/containers/", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert len(response.json()) == 5


def test_security_headers_on_cors_preflight(anonymous_client: TestClient) -> None:
    """Preflight replies come from an inner middleware; the outer wrapper still labels them."""
    response = anonymous_client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_security_headers_on_error_responses(anonymous_client: TestClient) -> None:
    """Handler-generated error responses also carry the security headers."""
    response = anonymous_client.get("/api/containers/")
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
