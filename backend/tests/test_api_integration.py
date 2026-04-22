"""
HTTP integration tests for the FastAPI app (full routing, serialization, dependency wiring).

Orchestrator / image builder are mocked so tests do not require Docker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.deps import get_image_builder, get_orchestrator, get_traffic_router
from app.core.default_image_builder import DefaultImageBuilder
from app.core.enums import BuildStrategy, SupportedLanguage
from app.core.exceptions import ImageNotFoundError, RegistryAccessDeniedError
from app.core.models import BuildResult, ProjectInfo
from app.core.orchestrator import ContainerOrchestrator
from app.core.traffic_router import NoopTrafficRouter


def test_health_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_containers(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "vela-test"


def test_list_containers_filter_status(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/", params={"status": "running"})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_image_availability_ok(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/containers/image/availability", params={"ref": "nginx:alpine"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["checked"] is True
    assert body["ref"] == "nginx:alpine"
    assert body["detail"] is None


def test_image_availability_not_found() -> None:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.verify_image_reference_available = AsyncMock(
        side_effect=ImageNotFoundError("bad:missing")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch
    with TestClient(app) as client:
        response = client.get(
            "/api/containers/image/availability", params={"ref": "bad:missing"}
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["checked"] is True
    assert body["ref"] == "bad:missing"
    assert body["error_code"] == "image_not_found"
    assert body["can_attempt_deploy"] is False
    assert body["detail"] == "Image not found."


def test_image_availability_registry_access_denied() -> None:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.verify_image_reference_available = AsyncMock(
        side_effect=RegistryAccessDeniedError("ngin", registry_message="denied")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch
    with TestClient(app) as client:
        response = client.get(
            "/api/containers/image/availability", params={"ref": "ngin"}
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["checked"] is True
    assert body["error_code"] == "registry_access_denied"
    assert body["can_attempt_deploy"] is True
    assert body["detail"] == "Image not found."


def test_image_not_found_exception_has_structured_api_content() -> None:
    exc = ImageNotFoundError("foo:bar", registry_message="manifest unknown")
    content = exc.api_response_content()
    assert content["error_code"] == "image_not_found"
    assert content["image_ref"] == "foo:bar"
    assert content["detail"] == "Image not found."
    assert "registry_detail" not in content
    assert "hints" not in content


def test_image_availability_git_url_not_checked() -> None:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.verify_image_reference_available = AsyncMock()
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch
    with TestClient(app) as client:
        response = client.get(
            "/api/containers/image/availability",
            params={"ref": "https://github.com/org/repo.git"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] is False
    assert body["available"] is True
    orch.verify_image_reference_available.assert_not_called()


def test_get_container(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/cid-1")
    assert response.status_code == 200
    assert response.json()["id"] == "cid-1"


def test_run_from_image_public_route(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    response = api_client.post(
        "/api/containers/run",
        json={
            "source": "nginx:alpine",
            "public_route": True,
            "container_port": 80,
            "host_port": None,
            "route_path_prefix": "/",
            "route_tls": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "image"
    assert body["image"] == "nginx:alpine"
    assert body["route_wired"] is True
    assert body["public_url"].startswith("https://")
    assert "apps.example.com" in body["public_url"]


def test_run_from_git_url(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    response = api_client.post(
        "/api/containers/run",
        json={
            "source": "https://github.com/org/repo.git",
            "git_branch": "develop",
            "public_route": True,
            "container_port": 80,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "git"
    assert body["image"] == "vela/gitbuild:abc123"


def test_run_public_route_requires_domain(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VELA_PUBLIC_ROUTE_DOMAIN", raising=False)

    response = api_client.post(
        "/api/containers/run",
        json={"source": "nginx:alpine", "public_route": True},
    )
    assert response.status_code == 400
    assert "VELA_PUBLIC_ROUTE_DOMAIN" in response.json()["detail"]


def test_start_stop_restart_remove(api_client: TestClient) -> None:
    assert api_client.post("/api/containers/cid-1/start").status_code == 200
    assert api_client.post("/api/containers/cid-1/stop").status_code == 200
    assert api_client.post("/api/containers/cid-1/restart").status_code == 200
    assert api_client.delete("/api/containers/cid-1").status_code == 204


def test_container_logs_stats_health(api_client: TestClient) -> None:
    assert api_client.get("/api/containers/cid-1/logs").json()["logs"] == "log line\n"
    stats = api_client.get("/api/containers/cid-1/stats").json()
    assert stats["container_id"] == "cid-1"
    assert api_client.get("/api/containers/cid-1/health").json()["status"] == "healthy"


def test_deploy_with_public_route(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    response = api_client.post(
        "/api/containers/deploy",
        json={
            "image": "nginx:alpine",
            "public_route": True,
            "route_path_prefix": "/",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route_wired"] is True
    assert body["public_url"].startswith("https://")


def test_run_rejects_empty_source(api_client: TestClient) -> None:
    response = api_client.post("/api/containers/run", json={"source": ""})
    assert response.status_code == 422


def test_builder_build_calls_pipeline() -> None:
    mock_orch = MagicMock()
    mock_orch.build_image = AsyncMock(return_value="sha256:x")
    builder = MagicMock(spec=DefaultImageBuilder)
    builder.build_from_source = AsyncMock(
        return_value=BuildResult(
            image_id="sha256:x",
            image_tag="t:1",
            strategy=BuildStrategy.GENERATED_DOCKERFILE,
            build_log="ok",
            project_info=ProjectInfo(language=SupportedLanguage.JAVASCRIPT),
        )
    )

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch
    app.dependency_overrides[get_image_builder] = lambda: builder

    with TestClient(app) as client:
        response = client.post(
            "/api/builder/build",
            json={
                "source": {"local_path": "C:/fake"},
                "tag": "my/app:1",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["image_tag"] == "t:1"
    builder.build_from_source.assert_awaited_once()


def test_builder_analyze_uses_validate_local(tmp_path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    mock_builder = MagicMock(spec=DefaultImageBuilder)
    mock_builder.analyze = AsyncMock(
        return_value=ProjectInfo(language=SupportedLanguage.JAVASCRIPT, has_dockerfile=False)
    )

    app = create_app()
    app.dependency_overrides[get_image_builder] = lambda: mock_builder

    with TestClient(app) as client:
        with patch.dict("os.environ", {"VELA_ALLOWED_BUILD_ROOT": str(tmp_path.parent)}):
            response = client.post(
                "/api/builder/analyze",
                json={"project_path": str(tmp_path)},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["language"] == "javascript"


def test_list_images() -> None:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.list_images = AsyncMock(return_value=["a:latest", "b:1"])

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch

    with TestClient(app) as client:
        response = client.get("/api/images/")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"images": ["a:latest", "b:1"]}


def test_pull_image() -> None:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.pull_image = AsyncMock(return_value=None)

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch

    with TestClient(app) as client:
        response = client.post(
            "/api/images/pull",
            params={"image": "nginx", "tag": "alpine"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["detail"] == "ok"
    orch.pull_image.assert_awaited_once()


def test_build_image_from_context(tmp_path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.build_image = AsyncMock(return_value="sha256:abc")

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orch

    with TestClient(app) as client:
        response = client.post(
            "/api/images/build",
            json={
                "context_path": str(tmp_path),
                "tag": "local/test:1",
                "dockerfile": "Dockerfile",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["tag"] == "local/test:1"


def test_traffic_routes_crud() -> None:
    router = NoopTrafficRouter()
    app = create_app()
    app.dependency_overrides[get_traffic_router] = lambda: router

    spec = {
        "route_id": "r1",
        "host": "app.test",
        "path_prefix": "/",
        "backend_host": "svc",
        "backend_port": 8080,
        "tls_enabled": False,
        "entrypoints": ["web"],
    }

    with TestClient(app) as client:
        created = client.post("/api/routes", json=spec)
        assert created.status_code == 200
        listed = client.get("/api/routes")
        assert len(listed.json()) == 1
        one = client.get("/api/routes/r1")
        assert one.status_code == 200
        assert one.json()["host"] == "app.test"
        deleted = client.delete("/api/routes/r1")
        assert deleted.status_code == 204
        empty = client.get("/api/routes")
        assert empty.json() == []

    app.dependency_overrides.clear()
