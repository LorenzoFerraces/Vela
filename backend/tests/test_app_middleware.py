"""App-level middleware tests (GZip response compression)."""

from __future__ import annotations

import uuid

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
