"""
HTTP integration tests for the FastAPI app (full routing, serialization, dependency wiring).

Uses in-memory SQLite and FakeContainerOrchestrator — no Docker daemon required.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.app import create_app
from app.core.auth.tokens import create_access_token
from app.core.containers.docker_orchestrator import (
    VELA_OWNER_LABEL,
    VELA_ROUTE_HOST_LABEL,
    VELA_ROUTE_PATH_PREFIX_LABEL,
    VELA_ROUTE_TLS_LABEL,
)
from app.core.exceptions import CloneError, ImageNotFoundError, RegistryAccessDeniedError
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.containers.volume_uploads import (
    VOLUME_UPLOAD_MAX_BYTES,
    VOLUME_UPLOAD_USER_QUOTA_BYTES,
)
from app.core.traffic.traffic_router import NoopTrafficRouter
from app.db.models import User
from tests.conftest import make_container_info


async def _stub_git_shallow_clone(
    *,
    url: str,
    branch: str,
    dest: Path,
    access_token: str | None = None,
) -> None:
    """
    Create a minimal stub repository at `dest` by writing a tiny Dockerfile.
    
    Used in tests to simulate a shallow git clone; this function ignores `url`, `branch`, and `access_token` and only ensures `dest` exists and contains a Dockerfile.
    
    Parameters:
        url (str): Source repository URL (ignored).
        branch (str): Git branch name (ignored).
        dest (Path): Destination directory to create and populate.
        access_token (str | None): Optional access token for private repos (ignored).
    """
    _ = url, branch, access_token
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")


def test_health_returns_ok() -> None:
    """Health endpoint is public (no DB or auth required)."""
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


def test_list_containers_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/containers/")
    assert response.status_code == 401


def test_other_user_does_not_see_containers(other_user_client: TestClient) -> None:
    """A different user's bearer token must not see another user's containers."""
    response = other_user_client.get("/api/containers/")
    assert response.status_code == 200
    assert response.json() == []


def test_other_user_cannot_get_container(other_user_client: TestClient) -> None:
    """Cross-user access on a single-container endpoint returns 404 (no existence leak)."""
    response = other_user_client.get("/api/containers/cid-1")
    assert response.status_code == 404


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


def test_image_availability_not_found(make_authed_client) -> None:
    """
    Verify the image availability endpoint reports a missing image with the expected structured error response.
    
    Asserts that for a reference which the orchestrator reports as not found: `available` is `False`, `checked` is `True`, `ref` matches the requested reference, `error_code` equals `"image_not_found"`, `can_attempt_deploy` is `False`, and `detail` contains the human-readable message `"Image not found."`.
    """
    orchestrator = FakeContainerOrchestrator()
    orchestrator.set_verify_error("bad:missing", ImageNotFoundError("bad:missing"))
    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get(
            "/api/containers/image/availability", params={"ref": "bad:missing"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["checked"] is True
    assert body["ref"] == "bad:missing"
    assert body["error_code"] == "image_not_found"
    assert body["can_attempt_deploy"] is False
    assert body["detail"] == "Image not found."


def test_image_availability_registry_access_denied(make_authed_client) -> None:
    orchestrator = FakeContainerOrchestrator()
    orchestrator.set_verify_error(
        "ngin",
        RegistryAccessDeniedError("ngin", registry_message="denied"),
    )
    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get(
            "/api/containers/image/availability", params={"ref": "ngin"}
        )
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


def test_image_availability_git_url_not_checked(
    make_authed_client, fake_orchestrator: FakeContainerOrchestrator
) -> None:
    """
    Verifies the image availability API treats Git repository URLs as not-checked and available.
    
    Calls the availability endpoint with a Git URL and asserts the response has "checked" == False and "available" == True, and that the orchestrator received no verify calls.
    """
    with make_authed_client(orchestrator=fake_orchestrator) as client:
        response = client.get(
            "/api/containers/image/availability",
            params={"ref": "https://github.com/org/repo.git"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] is False
    assert body["available"] is True
    assert fake_orchestrator.verify_calls == []


def test_get_container(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/cid-1")
    assert response.status_code == 200
    assert response.json()["id"] == "cid-1"


def test_run_from_image_with_env_and_command(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "public_route": True,
            "container_port": 80,
            "env_vars": {"NODE_ENV": "production", "APP_HOST": "0.0.0.0"},
            "command": ["nginx", "-g", "daemon off;"],
        },
    )
    assert response.status_code == 200
    assert fake_orchestrator.last_deploy_config is not None
    assert fake_orchestrator.last_deploy_config.env_vars == {
        "NODE_ENV": "production",
        "APP_HOST": "0.0.0.0",
    }
    assert fake_orchestrator.last_deploy_config.command == [
        "nginx",
        "-g",
        "daemon off;",
    ]


def test_run_rejects_empty_env_key(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "env_vars": {"": "value"},
        },
    )
    assert response.status_code == 422


def test_run_rejects_duplicate_env_keys_after_trim(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "env_vars": {"FOO": "one", " FOO ": "two"},
        },
    )
    assert response.status_code == 422


def test_run_rejects_empty_command(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "command": [],
        },
    )
    assert response.status_code == 422


def test_run_from_image_with_read_only_volumes(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))

    upload_response = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("myfolder/hello.txt", b"hello"))],
    )
    assert upload_response.status_code == 200
    upload_id = upload_response.json()["upload_id"]

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "volumes": [{"upload_id": upload_id, "target": "/data"}],
        },
    )
    assert response.status_code == 200
    assert fake_orchestrator.last_deploy_config is not None
    assert len(fake_orchestrator.last_deploy_config.volumes) == 1
    assert fake_orchestrator.last_deploy_config.volumes[0].target == "/data"
    assert fake_orchestrator.last_deploy_config.volumes[0].source.endswith(
        str(upload_id)
    )


def test_volume_upload_rejects_empty_folder(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    response = api_client.post("/api/containers/volume-uploads", files=[])
    assert response.status_code == 422


def test_volume_upload_rejects_oversized_folder(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    oversized = b"x" * (VOLUME_UPLOAD_MAX_BYTES + 1)
    response = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("big/file.bin", oversized))],
    )
    assert response.status_code == 400


def test_volume_upload_rejects_when_user_quota_exceeded(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    first_size = VOLUME_UPLOAD_USER_QUOTA_BYTES - (50 * 1024 * 1024)
    first_response = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("first/big.bin", b"x" * first_size))],
    )
    assert first_response.status_code == 200

    second_response = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("second/big.bin", b"x" * (60 * 1024 * 1024)))],
    )
    assert second_response.status_code == 400


def test_run_rejects_volume_without_upload_id(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "volumes": [{"target": "/data"}],
        },
    )
    assert response.status_code == 422


def test_run_rejects_relative_volume_target(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    upload_response = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder/a.txt", b"a"))],
    )
    upload_id = upload_response.json()["upload_id"]

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "volumes": [{"upload_id": upload_id, "target": "data"}],
        },
    )
    assert response.status_code == 422


def test_run_rejects_duplicate_volume_targets(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    first_upload = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder-a/a.txt", b"a"))],
    )
    second_upload = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder-b/b.txt", b"b"))],
    )
    first_id = first_upload.json()["upload_id"]
    second_id = second_upload.json()["upload_id"]

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "volumes": [
                {"upload_id": first_id, "target": "/data"},
                {"upload_id": second_id, "target": "/data"},
            ],
        },
    )
    assert response.status_code == 422


def test_run_from_image_public_route(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    test_user_id,
    monkeypatch: pytest.MonkeyPatch,
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

    assert fake_orchestrator.last_deploy_config is not None
    assert fake_orchestrator.last_deploy_config.labels.get(VELA_OWNER_LABEL) == str(
        test_user_id
    )


def test_run_from_dockerfile_template(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    create = api_client.post(
        "/api/dockerfiles/",
        json={"name": "minimal", "contents": "FROM alpine:3.20\n"},
    )
    template_id = create.json()["id"]

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "dockerfile_template",
            "dockerfile_template_id": template_id,
            "public_route": True,
            "container_port": 80,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "dockerfile_template"
    assert body["image"].startswith("vela/templatebuild:")
    assert any(tag.startswith("vela/templatebuild:") for tag in fake_orchestrator._built_tags)

    history = api_client.get("/api/deployments/")
    assert history.status_code == 200
    template_rows = [
        row
        for row in history.json()
        if row["source_kind"] == "dockerfile_template"
    ]
    assert template_rows
    assert template_rows[0]["source_ref"] == "minimal"

    listed_containers = api_client.get("/api/containers/")
    assert listed_containers.status_code == 200
    deployed = next(
        row
        for row in listed_containers.json()
        if row["image"].startswith("vela/templatebuild:")
    )
    assert deployed["source_kind"] == "dockerfile_template"
    assert deployed["source_label"] == "minimal"


def test_run_from_git_url(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")
    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone",
        _stub_git_shallow_clone,
    )

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
    assert body["image"].startswith("vela/gitbuild:")


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


def test_container_logs_tail_validation(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/cid-1/logs", params={"tail": 99999})
    assert response.status_code == 422


def test_list_containers_includes_access_url(
    make_authed_client,
    test_user_id: uuid.UUID,
) -> None:
    """
    Ensure the container listing includes an access_url when a container is seeded with route labels.
    
    Seeds a FakeContainerOrchestrator with a container record that has route-related labels and an access_url, requests the containers list endpoint, and asserts the returned entry contains the same access_url.
    """
    orchestrator = FakeContainerOrchestrator()
    row = make_container_info(
        owner_id=test_user_id,
        labels={
            VELA_ROUTE_HOST_LABEL: "svc.example.com",
            VELA_ROUTE_PATH_PREFIX_LABEL: "/",
            VELA_ROUTE_TLS_LABEL: "true",
        },
        access_url="https://svc.example.com/",
    )
    orchestrator.seed_container(row)
    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get("/api/containers/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["access_url"] == "https://svc.example.com/"


def test_logs_stream_authenticated(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/logs/stream?access_token={auth_token}&follow=false"
    ) as websocket:
        data = websocket.receive_bytes()
    assert data == b"log line\n"


def test_logs_stream_requires_token(anonymous_client: TestClient) -> None:
    with anonymous_client.websocket_connect(
        "/api/containers/cid-1/logs/stream"
    ) as websocket:
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_bytes()


def test_logs_stream_wrong_owner(
    api_client: TestClient,
    other_user_client: TestClient,
    seeded_other_user: User,
) -> None:
    token = create_access_token(seeded_other_user.id)
    with other_user_client.websocket_connect(
        f"/api/containers/cid-1/logs/stream?access_token={token}"
    ) as websocket:
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_bytes()
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


def test_run_from_github_uses_stored_token(
    api_client: TestClient,
    db_session_factory,
    seeded_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connected user's GitHub URL forwards the decrypted token to git clone."""
    import asyncio

    from cryptography.fernet import Fernet

    from app.core.oauth.identity import GITHUB_PROVIDER
    from app.core.security import reset_token_cipher_for_tests
    from app.core.security.secrets import encrypt_secret
    from app.db.models import UserOAuthIdentity

    recorded_tokens: list[str | None] = []

    async def recording_clone(
        *,
        url: str,
        branch: str,
        dest: Path,
        access_token: str | None = None,
    ) -> None:
        """
        Record the provided git access token and perform a shallow clone into the destination.
        
        Records the value of `access_token` by appending it to the test-scoped `recorded_tokens` list, then delegates to the test helper `_stub_git_shallow_clone` to create a minimal cloned workspace at `dest`.
        
        Parameters:
            url (str): Source repository URL (not otherwise validated).
            branch (str): Branch name to check out.
            dest (Path): Filesystem path where the stub clone will be created.
            access_token (str | None): Optional Git access token forwarded to the clone helper; `None` when no token is provided.
        """
        _ = url, branch
        recorded_tokens.append(access_token)
        await _stub_git_shallow_clone(
            url=url, branch=branch, dest=dest, access_token=access_token
        )

    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")
    monkeypatch.setenv("VELA_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_token_cipher_for_tests()
    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone",
        recording_clone,
    )

    async def seed_identity() -> None:
        """
        Insert a GitHub OAuth identity for the seeded test user into the test database.
        
        Creates and commits a UserOAuthIdentity record for `seeded_user` with:
        - provider: GITHUB
        - provider_subject: "42"
        - username: "octocat"
        - scopes: "repo,read:user"
        - access_token_encrypted: encryption of "ghp_secret_value"
        """
        async with db_session_factory() as session:
            session.add(
                UserOAuthIdentity(
                    user_id=seeded_user.id,
                    provider=GITHUB_PROVIDER,
                    provider_subject="42",
                    username="octocat",
                    avatar_url=None,
                    scopes="repo,read:user",
                    access_token_encrypted=encrypt_secret("ghp_secret_value"),
                )
            )
            await session.commit()

    asyncio.run(seed_identity())

    response = api_client.post(
        "/api/containers/run",
        json={
            "source": "https://github.com/octo/private-repo.git",
            "git_branch": "main",
            "public_route": True,
            "container_port": 80,
        },
    )

    assert response.status_code == 200, response.text
    assert recorded_tokens == ["ghp_secret_value"]


def test_run_from_github_without_connection_does_not_send_token(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disconnected users keep working for public repos and pass no token."""
    recorded_tokens: list[str | None] = []

    async def recording_clone(
        *,
        url: str,
        branch: str,
        dest: Path,
        access_token: str | None = None,
    ) -> None:
        """
        Record the provided git access token and perform a shallow clone into the destination.
        
        Records the value of `access_token` by appending it to the test-scoped `recorded_tokens` list, then delegates to the test helper `_stub_git_shallow_clone` to create a minimal cloned workspace at `dest`.
        
        Parameters:
            url (str): Source repository URL (not otherwise validated).
            branch (str): Branch name to check out.
            dest (Path): Filesystem path where the stub clone will be created.
            access_token (str | None): Optional Git access token forwarded to the clone helper; `None` when no token is provided.
        """
        _ = url, branch
        recorded_tokens.append(access_token)
        await _stub_git_shallow_clone(
            url=url, branch=branch, dest=dest, access_token=access_token
        )

    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")
    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone",
        recording_clone,
    )

    response = api_client.post(
        "/api/containers/run",
        json={
            "source": "https://github.com/org/public-repo.git",
            "git_branch": "main",
            "public_route": True,
            "container_port": 80,
        },
    )

    assert response.status_code == 200, response.text
    assert recorded_tokens == [None]


def test_run_private_github_clone_failure_hints_settings(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An auth-style CloneError on github.com surfaces a friendly Settings hint."""
    async def failing_clone(**_kwargs: object) -> None:
        """
        Simulate a failing git shallow clone by always raising a CloneError.
        
        This test helper accepts any keyword arguments (ignored) and immediately raises a CloneError
        with a message indicating authentication failure for the private GitHub URL.
        
        Raises:
            CloneError: Indicates authentication failed for 'https://github.com/org/private.git/'.
        """
        raise CloneError(
            "https://github.com/org/private.git",
            "fatal: Authentication failed for 'https://github.com/org/private.git/'",
        )

    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")
    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone",
        failing_clone,
    )

    response = api_client.post(
        "/api/containers/run",
        json={
            "source": "https://github.com/org/private.git",
            "git_branch": "main",
            "public_route": True,
            "container_port": 80,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "connect github in settings" in detail


def test_builder_build_calls_pipeline(make_authed_client, tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "app"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    monkeypatch.setenv("VELA_ALLOWED_BUILD_ROOT", str(tmp_path.parent))

    with make_authed_client() as client:
        response = client.post(
            "/api/builder/build",
            json={
                "source": {"local_path": str(project_dir)},
                "tag": "my/app:1",
            },
        )

    assert response.status_code == 200
    assert response.json()["image_tag"] == "my/app:1"


def test_builder_analyze_uses_validate_local(
    make_authed_client, tmp_path, monkeypatch
) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")

    monkeypatch.setenv("VELA_ALLOWED_BUILD_ROOT", str(tmp_path.parent))

    with make_authed_client() as client:
        response = client.post(
            "/api/builder/analyze",
            json={"project_path": str(tmp_path)},
        )

    assert response.status_code == 200
    assert response.json()["language"] == "javascript"


def test_image_suggestions_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/containers/image/suggestions")
    assert response.status_code == 401


def test_image_suggestions_merges_local_and_hub(
    make_authed_client, monkeypatch
) -> None:
    """
    Verifies that the image suggestions endpoint merges local orchestrator images with Docker Hub suggestions and prefers local images before identical upstream matches.
    
    Calls the suggestions API for query "nginx" and asserts the response includes both the locally registered image "my/nginx:dev" and the hub suggestion "nginx", with "my/nginx:dev" appearing earlier in the returned list.
    """
    orchestrator = FakeContainerOrchestrator()
    orchestrator.register_image("my/nginx:dev")
    orchestrator.register_image("nginx:alpine")

    async def fake_hub(query: str, *, page_size: int) -> list[tuple[str, int]]:
        """
        Provide fake Docker Hub suggestions for the given image query.
        
        Parameters:
        	query (str): Search term to query for image suggestions; expected to be "nginx" in tests.
        	page_size (int): Maximum number of suggestions requested; tests assert this is at least 25.
        
        Returns:
        	list[tuple[str, int]]: A list of (image_ref, popularity_score) tuples representing suggested images.
        """
        assert query == "nginx"
        assert page_size >= 25
        return [("nginx", 1_000_000), ("other/nginx", 100)]

    monkeypatch.setattr(
        "app.api.routes.containers.fetch_docker_hub_suggestions",
        fake_hub,
    )

    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get("/api/containers/image/suggestions?q=nginx&limit=10")

    assert response.status_code == 200
    body = response.json()["suggestions"]
    refs = [item["ref"] for item in body]
    assert "my/nginx:dev" in refs
    assert "nginx" in refs
    assert refs.index("my/nginx:dev") < refs.index("nginx")


def test_image_suggestions_empty_query_skips_hub(
    make_authed_client, monkeypatch
) -> None:
    """
    Verifies that image suggestion endpoint returns local images and does not query Docker Hub when no search query is provided.
    
    Exercises the API /api/containers/image/suggestions with an empty query, asserting HTTP 200 and that registered local image refs (e.g., "local-only:1") appear in the returned suggestions. Also ensures the Docker Hub suggestion function is not invoked for empty queries by replacing it with a stub that would fail if called.
    """
    orchestrator = FakeContainerOrchestrator()
    orchestrator.register_image("local-only:1")

    async def fake_hub(*_args: object, **_kwargs: object) -> list[tuple[str, int]]:
        """
        Stub replacement for Docker Hub suggestion fetch that fails if invoked.
        
        Raises:
            AssertionError: always raised with message "Hub should not be called for an empty query".
        """
        raise AssertionError("Hub should not be called for an empty query")

    monkeypatch.setattr(
        "app.api.routes.containers.fetch_docker_hub_suggestions",
        fake_hub,
    )

    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get("/api/containers/image/suggestions")

    assert response.status_code == 200
    refs = {item["ref"] for item in response.json()["suggestions"]}
    assert "local-only:1" in refs


def test_list_images(make_authed_client) -> None:
    """
    Verify that GET /api/images/ returns all images registered with the orchestrator.
    
    Registers two images in a FakeContainerOrchestrator, queries the images endpoint, and asserts the response is HTTP 200 and includes both image references.
    """
    orchestrator = FakeContainerOrchestrator()
    orchestrator.register_image("a:latest")
    orchestrator.register_image("b:1")

    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.get("/api/images/")

    assert response.status_code == 200
    images = response.json()["images"]
    assert "a:latest" in images
    assert "b:1" in images


def test_pull_image(make_authed_client) -> None:
    """
    Verifies that POST /api/images/pull pulls the specified image and registers it with the orchestrator.
    
    Asserts the endpoint responds with HTTP 200 and JSON {"detail": "ok"}, and that the orchestrator's image set includes "nginx:alpine".
    """
    orchestrator = FakeContainerOrchestrator()

    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.post(
            "/api/images/pull",
            params={"image": "nginx", "tag": "alpine"},
        )

    assert response.status_code == 200
    assert response.json()["detail"] == "ok"
    assert "nginx:alpine" in orchestrator._images


def test_build_image_from_context(make_authed_client, tmp_path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    orchestrator = FakeContainerOrchestrator()

    with make_authed_client(orchestrator=orchestrator) as client:
        response = client.post(
            "/api/images/build",
            json={
                "context_path": str(tmp_path),
                "tag": "local/test:1",
                "dockerfile": "Dockerfile",
            },
        )

    assert response.status_code == 200
    assert response.json()["tag"] == "local/test:1"
    assert "local/test:1" in orchestrator._images


def test_traffic_routes_crud(make_authed_client) -> None:
    router = NoopTrafficRouter()

    spec = {
        "route_id": "r1",
        "host": "app.test",
        "path_prefix": "/",
        "backend_host": "svc",
        "backend_port": 8080,
        "tls_enabled": False,
        "entrypoints": ["web"],
    }

    with make_authed_client(traffic_router=router) as client:
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
