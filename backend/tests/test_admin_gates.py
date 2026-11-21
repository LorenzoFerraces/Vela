from fastapi.testclient import TestClient

from app.core.auth.tokens import create_access_token
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.db.models import User


def test_student_cannot_upsert_route(api_client: TestClient, seeded_user: User) -> None:
    api_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_user.id)}"
    spec = RouteSpec(
        route_id="r1", host="app.example.test", path_prefix="/",
        backend_servers=[BackendServer(host="nginx", port=80)], tls_enabled=False,
    )
    response = api_client.post("/api/routes", json=spec.model_dump(mode="json"))
    assert response.status_code == 403
