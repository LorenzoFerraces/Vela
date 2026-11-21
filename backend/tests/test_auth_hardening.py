import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import rate_limit
from app.core.auth.tokens import create_access_token, decode_access_token
from app.core.auth.ws_tickets import consume_ws_ticket, issue_ws_ticket
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo, ContainerStatus
from app.db.models import User


def test_rate_limit_blocks_eleventh_attempt() -> None:
    rate_limit.reset_for_tests()
    for _ in range(10):
        rate_limit.check_rate_limit("1.2.3.4")
    with pytest.raises(Exception) as exc:
        rate_limit.check_rate_limit("1.2.3.4")
    assert getattr(exc.value, "status_code", None) == 429


def test_rate_limit_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_limit.reset_for_tests()
    monkeypatch.setenv("VELA_DISABLE_RATE_LIMIT", "1")
    for _ in range(11):
        rate_limit.check_rate_limit("1.2.3.4")


def test_jwt_carries_and_verifies_issuer_audience() -> None:
    claims = decode_access_token(create_access_token(uuid.uuid4()))
    assert claims.issuer == "vela"
    assert claims.audience == "vela-api"


def test_ws_ticket_is_single_use_and_scoped() -> None:
    user_id, container_id = uuid.uuid4(), "cid-1"
    ticket = issue_ws_ticket(user_id, container_id, "logs")
    assert consume_ws_ticket(ticket, container_id, "logs") == user_id
    assert consume_ws_ticket(ticket, container_id, "logs") is None
    other = issue_ws_ticket(user_id, container_id, "logs")
    assert consume_ws_ticket(other, "cid-2", "logs") is None
    assert consume_ws_ticket(other, container_id, "exec") is None


def test_ws_ticket_endpoint_requires_auth(
    api_client: TestClient,
    anonymous_client: TestClient,
    seeded_user: User,
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    """Seed via the existing fake-orchestrator fixture; assert both anonymous rejection and auth success."""
    fake_orchestrator.seed_container(ContainerInfo.model_validate({
        "id": "cid-1", "name": "api", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00",
        "labels": {"vela.project_id": str(seeded_user.personal_project_id)},
        "ports": [],
    }))
    url = "/api/containers/cid-1/ws-ticket?purpose=logs"
    assert anonymous_client.post(url).status_code == 401
    assert api_client.post(url).status_code == 200


def test_expired_unconsumed_ws_ticket_is_swept(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.core.auth import ws_tickets

    ws_tickets.reset_for_tests()
    clock = {"now": 1000.0}
    monkeypatch.setattr(ws_tickets, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    old = ws_tickets.issue_ws_ticket(uuid.uuid4(), "cid-1", "logs")
    assert old in ws_tickets._tickets
    clock["now"] += ws_tickets._TICKET_TTL_SECONDS + 1
    ws_tickets.issue_ws_ticket(uuid.uuid4(), "cid-1", "logs")
    assert old not in ws_tickets._tickets
    assert len(ws_tickets._tickets) == 1


def test_login_throttled(anonymous_client: TestClient) -> None:
    rate_limit.reset_for_tests()
    for _ in range(11):
        response = anonymous_client.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
        )
    assert response.status_code == 429
