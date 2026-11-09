"""Contract: compose Traefik uses one file-provider directory, not filename + directory."""

from __future__ import annotations

from pathlib import Path

import yaml


def _compose() -> dict:
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    return yaml.safe_load(compose_path.read_text(encoding="utf-8"))


def _traefik_service() -> dict:
    return _compose()["services"]["traefik"]


def test_traefik_file_provider_uses_single_dynamic_directory() -> None:
    traefik = _traefik_service()
    command = traefik["command"]
    volumes = traefik["volumes"]

    assert "--providers.file.directory=/etc/traefik/dynamic" in command
    assert not any(
        entry.startswith("--providers.file.filename") for entry in command
    )
    assert "--providers.file.directory=/etc/traefik/static" not in command
    assert "./traefik/static/spa.yaml:/etc/traefik/dynamic/spa.yaml:ro" in volumes
    assert "traefik_dynamic:/etc/traefik/dynamic" in volumes


def test_api_writes_traefik_dynamic_file_with_yaml_extension() -> None:
    dynamic_file = _compose()["services"]["api"]["environment"][
        "VELA_TRAEFIK_DYNAMIC_FILE"
    ]
    assert dynamic_file == "/etc/traefik/dynamic/traefik-http.yml"
