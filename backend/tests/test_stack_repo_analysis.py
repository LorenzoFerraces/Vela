"""Tests for repository manifest detection and LLM stack generation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_image_builder
from app.core.exceptions import LlmCallError
from app.core.git.git_source_analysis import _collect_context_excerpts
from app.core.stacks import repo_analysis
from app.core.stacks.repo_analysis import (
    _generate_services,
    _payload_to_services,
    detect_manifest_file,
)

COMPOSE_FILE = """
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
  db:
    image: postgres:16
"""

K8S_FILE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  template:
    spec:
      containers:
        - name: web
          image: nginx:alpine
          ports:
            - containerPort: 8080
"""

LLM_PAYLOAD = {
    "services": [
        {
            "service_name": "web",
            "source_kind": "git",
            "source_ref": "",
            "container_port": 8000,
            "env_var_entries": [{"key": "DATABASE_URL", "value": ""}],
            "command": None,
            "public_route": True,
            "depends_on": ["db"],
        },
        {
            "service_name": "db",
            "source_kind": "image",
            "source_ref": "postgres:16",
            "container_port": 5432,
            "env_var_entries": [],
            "command": None,
            "public_route": False,
            "depends_on": None,
        },
    ],
    "summary_hint": "Web application with PostgreSQL.",
}


def test_root_docker_compose_wins(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    path, kind = detect_manifest_file(tmp_path) or (None, None)
    assert path == tmp_path / "docker-compose.yml"
    assert kind == "compose"


def test_top_level_compose_is_found(tmp_path: Path) -> None:
    directory = tmp_path / "deploy"
    directory.mkdir()
    (directory / "compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    result = detect_manifest_file(tmp_path)
    assert result == (directory / "compose.yml", "compose")


def test_preferred_k8s_directory_wins(tmp_path: Path) -> None:
    (tmp_path / "random.yaml").write_text(K8S_FILE, encoding="utf-8")
    directory = tmp_path / "k8s"
    directory.mkdir()
    (directory / "app.yaml").write_text(K8S_FILE, encoding="utf-8")
    assert detect_manifest_file(tmp_path) == (directory / "app.yaml", "k8s")


def test_non_manifest_yaml_and_ignored_directories_are_skipped(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "plain.yaml").write_text("name: value\n", encoding="utf-8")
    assert detect_manifest_file(tmp_path) is None


def test_compose_wins_over_k8s(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "k8s.yaml").write_text(K8S_FILE, encoding="utf-8")
    result = detect_manifest_file(tmp_path)
    assert result is not None
    assert result[1] == "compose"


def test_payload_to_services_git_service_uses_repo_url() -> None:
    warnings: list[str] = []
    services = _payload_to_services(
        LLM_PAYLOAD,
        git_url="https://github.com/org/repo.git",
        git_branch="develop",
        warnings=warnings,
    )
    by_name = {service.service_name: service for service in services}
    web = by_name["web"]
    assert web.source_kind == "git"
    assert web.source_ref == "https://github.com/org/repo.git"
    assert web.git_branch == "develop"
    assert web.container_port == 8000
    assert web.env_vars == {"DATABASE_URL": ""}
    assert web.public_route is True
    assert web.depends_on == ["db"]
    db = by_name["db"]
    assert db.source_kind == "image"
    assert db.source_ref == "postgres:16"
    assert db.git_branch is None
    assert warnings == []


def test_payload_to_services_skips_invalid_source_kind() -> None:
    warnings: list[str] = []
    payload = {
        "services": [
            {
                "service_name": "broken",
                "source_kind": "volume",
                "source_ref": "/data",
                "container_port": 80,
            },
            LLM_PAYLOAD["services"][1],
        ]
    }
    services = _payload_to_services(
        payload,
        git_url="https://github.com/org/repo.git",
        git_branch="main",
        warnings=warnings,
    )
    assert [service.service_name for service in services] == ["db"]
    assert len(warnings) == 1
    assert "broken" in warnings[0]


def test_payload_to_services_invalid_port_becomes_80() -> None:
    payload = {
        "services": [
            {
                "service_name": "web",
                "source_kind": "git",
                "source_ref": "",
                "container_port": 70000,
            }
        ]
    }
    services = _payload_to_services(
        payload,
        git_url="https://github.com/org/repo.git",
        git_branch="main",
        warnings=[],
    )
    assert services[0].container_port == 80


def test_payload_to_services_empty_result_raises() -> None:
    with pytest.raises(LlmCallError):
        _payload_to_services(
            {"services": []},
            git_url="https://github.com/org/repo.git",
            git_branch="main",
            warnings=[],
        )


class StubImageBuilder:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def clone_repository(
        self,
        git_url: str,
        *,
        branch: str = "main",
        access_token: str | None = None,
    ) -> str:
        _ = git_url, branch, access_token
        return str(self._root)


def _post_analyze_repo(
    api_client: TestClient,
    stub_root: Path,
) -> object:
    api_client.app.dependency_overrides[get_image_builder] = lambda: StubImageBuilder(
        stub_root
    )
    try:
        return api_client.post(
            "/api/stacks/analyze-repo",
            json={"git_url": "https://github.com/org/repo.git", "git_branch": "main"},
        )
    finally:
        api_client.app.dependency_overrides.pop(get_image_builder, None)


def test_analyze_repo_e2e_fixture(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_E2E", "1")
    response = api_client.post(
        "/api/stacks/analyze-repo",
        json={"git_url": "https://github.com/org/repo.git", "git_branch": "main"},
    )
    assert response.status_code == 200
    assert response.json()["manifest_kind"] == "llm"
    assert {s["service_name"] for s in response.json()["services"]} == {"web", "redis"}


def test_analyze_repo_no_manifest_without_llm_returns_503(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("No deployment markers.\n", encoding="utf-8")
    monkeypatch.delenv("VELA_E2E", raising=False)
    monkeypatch.delenv("VELA_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_PROJECT_ID", raising=False)
    response = _post_analyze_repo(api_client, root)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_analyze_repo_compose_manifest(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    monkeypatch.delenv("VELA_E2E", raising=False)
    response = _post_analyze_repo(api_client, root)
    assert response.status_code == 200
    data = response.json()
    assert data["manifest_kind"] == "compose"
    assert data["manifest_path"] == "docker-compose.yml"
    assert any("docker-compose.yml" in warning for warning in data["warnings"])
    by_name = {service["service_name"]: service for service in data["services"]}
    assert by_name["web"]["source_kind"] == "image"
    assert by_name["web"]["source_ref"] == "nginx:alpine"
    assert by_name["web"]["container_port"] == 80
    assert by_name["db"]["source_ref"] == "postgres:16"


def test_compose_manifest_path_skips_head_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    monkeypatch.delenv("VELA_E2E", raising=False)
    monkeypatch.setattr(
        repo_analysis,
        "head_commit",
        lambda directory: pytest.fail("head_commit ran on the manifest path"),
    )
    analysis = asyncio.run(
        repo_analysis.analyze_repo_stack(
            StubImageBuilder(root),
            git_url="https://github.com/org/repo.git",
            git_branch="main",
            access_token=None,
        )
    )
    assert analysis.manifest_kind == "compose"


def test_generate_services_prompt_contains_detected_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(
        "# Setup\n\n| Variable | Notes |\n| --- | --- |\n"
        "| `DATABASE_URL` | `postgres://db:5432/app` |\n",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    captured: dict[str, str] = {}

    async def fake_generate_json(*, prompt: str, schema: dict) -> dict:
        captured["prompt"] = prompt
        return LLM_PAYLOAD

    monkeypatch.setattr(repo_analysis, "generate_json", fake_generate_json)
    asyncio.run(
        _generate_services(
            context=_collect_context_excerpts(root),
            manifest=None,
            git_url="https://github.com/org/repo.git",
            git_branch="main",
            warnings=[],
            root=root,
        )
    )
    assert "Detected facts" in captured["prompt"]
    assert "DATABASE_URL" in captured["prompt"]


def test_analyze_repo_k8s_manifest(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    directory = root / "k8s"
    directory.mkdir(parents=True)
    (directory / "app.yaml").write_text(K8S_FILE, encoding="utf-8")
    monkeypatch.delenv("VELA_E2E", raising=False)
    response = _post_analyze_repo(api_client, root)
    assert response.status_code == 200
    data = response.json()
    assert data["manifest_kind"] == "k8s"
    assert data["manifest_path"] == "k8s/app.yaml"
    service = data["services"][0]
    assert service["service_name"] == "web"
    assert service["source_ref"] == "nginx:alpine"
    assert service["container_port"] == 8080
