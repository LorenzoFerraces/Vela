"""Unit tests for docker-compose parsing into StackService records."""

from __future__ import annotations

from app.core.stacks.compose_parser import parse_compose


def test_parse_compose_image_env_ports_command_depends_on() -> None:
    yaml_content = """
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
    environment:
      APP_ENV: production
    command: nginx -g 'daemon off;'
    depends_on:
      - redis
  redis:
    image: redis:7
    expose:
      - "6379"
"""
    services, warnings = parse_compose(yaml_content)
    assert warnings == []
    by_name = {service.service_name: service for service in services}

    assert by_name["web"].source_kind == "image"
    assert by_name["web"].source_ref == "nginx:alpine"
    assert by_name["web"].container_port == 80
    assert by_name["web"].env_vars == {"APP_ENV": "production"}
    assert by_name["web"].command == ["nginx", "-g", "'daemon", "off;'"]
    assert by_name["web"].depends_on == ["redis"]

    assert by_name["redis"].source_kind == "image"
    assert by_name["redis"].source_ref == "redis:7"
    assert by_name["redis"].container_port == 6379


def test_parse_compose_list_environment_and_depends_on_map() -> None:
    yaml_content = """
services:
  api:
    image: python:3.12-slim
    environment:
      - FOO=bar
      - BAZ
    depends_on:
      db:
        condition: service_started
  db:
    image: postgres:15
"""
    services, warnings = parse_compose(yaml_content)
    assert warnings == []
    api = next(service for service in services if service.service_name == "api")
    assert api.env_vars == {"FOO": "bar", "BAZ": ""}
    assert api.depends_on == ["db"]


def test_parse_compose_build_context_as_dockerfile_template() -> None:
    yaml_content = """
services:
  app:
    build:
      context: ./app
"""
    services, warnings = parse_compose(yaml_content)
    assert len(services) == 1
    assert services[0].source_kind == "dockerfile_template"
    assert services[0].source_ref == "./app"
    assert warnings == []


def test_parse_compose_unsupported_features_emit_warnings() -> None:
    yaml_content = """
services:
  web:
    image: nginx:alpine
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
    networks:
      - frontend
"""
    services, warnings = parse_compose(yaml_content)
    assert len(services) == 1
    assert services[0].source_ref == "nginx:alpine"
    joined = " ".join(warnings)
    assert "volumes" in joined
    assert "healthcheck" in joined
    assert "networks" in joined


def test_parse_compose_invalid_top_level() -> None:
    services, warnings = parse_compose("- just a list")
    assert services == []
    assert warnings == ["Invalid compose file: expected a mapping at the top level."]


def test_parse_compose_defaults_when_no_image_or_build() -> None:
    yaml_content = """
services:
  orphan: {}
"""
    services, warnings = parse_compose(yaml_content)
    assert len(services) == 1
    assert services[0].source_kind == "image"
    assert services[0].source_ref == "nginx:alpine"
    assert any("no image or build" in warning for warning in warnings)
