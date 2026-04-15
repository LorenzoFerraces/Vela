"""Tests for TraefikFileTrafficRouter."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.core.exceptions import RouteConfigurationError, RouteNotFoundError
from app.core.traffic_models import RouteSpec
from app.core.traefik_file_traffic_router import (
    TraefikFileTrafficRouter,
    _build_traefik_document,
)


@pytest.fixture
def traefik_file_pair(tmp_path: Path) -> tuple[Path, TraefikFileTrafficRouter]:
    dynamic_file = tmp_path / "dynamic" / "vela-http.json"
    router = TraefikFileTrafficRouter(traefik_dynamic_file=dynamic_file)
    return dynamic_file, router


def test_upsert_and_list_roundtrip(traefik_file_pair: tuple[Path, TraefikFileTrafficRouter]) -> None:
    dynamic_file, router = traefik_file_pair
    spec = RouteSpec(
        route_id="demo-app",
        host="app.example.test",
        path_prefix="/",
        backend_host="vela-smoke",
        backend_port=80,
    )
    info = asyncio.run(router.upsert_route(spec))
    assert info.route_id == "demo-app"
    listed = asyncio.run(router.list_routes())
    assert len(listed) == 1
    assert listed[0].host == "app.example.test"
    assert dynamic_file.is_file()
    state_file = dynamic_file.parent / ".vela-traffic-state.json"
    assert state_file.is_file()
    traefik_payload = json.loads(dynamic_file.read_text(encoding="utf-8"))
    assert "http" in traefik_payload
    assert "vela_demo-app" in traefik_payload["http"]["routers"]


def test_build_traefik_document_tls_emits_web_and_websecure_routers() -> None:
    spec = RouteSpec(
        route_id="edge",
        host="app.wild.example",
        path_prefix="/",
        backend_host="be",
        backend_port=8080,
        tls_enabled=True,
        entrypoints=["web", "websecure"],
    )
    doc = _build_traefik_document([spec])
    routers = doc["http"]["routers"]
    assert routers["vela_edge_w"]["entryPoints"] == ["web"]
    assert "tls" not in routers["vela_edge_w"]
    assert routers["vela_edge_ws"]["entryPoints"] == ["websecure"]
    assert routers["vela_edge_ws"]["tls"] == {}
    assert routers["vela_edge_w"]["service"] == routers["vela_edge_ws"]["service"] == "vela_edge_svc"


def test_upsert_idempotent(traefik_file_pair: tuple[Path, TraefikFileTrafficRouter]) -> None:
    _, router = traefik_file_pair
    spec = RouteSpec(
        route_id="same",
        host="h.test",
        path_prefix="/api",
        backend_host="svc",
        backend_port=3000,
    )
    asyncio.run(router.upsert_route(spec))
    asyncio.run(router.upsert_route(spec))
    listed = asyncio.run(router.list_routes())
    assert len(listed) == 1


def test_build_traefik_document_empty_is_root_empty_object() -> None:
    assert _build_traefik_document([]) == {}


def test_remove_route(traefik_file_pair: tuple[Path, TraefikFileTrafficRouter]) -> None:
    dynamic_file, router = traefik_file_pair
    asyncio.run(
        router.upsert_route(
            RouteSpec(
                route_id="gone",
                host="gone.test",
                path_prefix="/",
                backend_host="x",
                backend_port=1,
            )
        )
    )
    asyncio.run(router.remove_route("gone"))
    assert asyncio.run(router.list_routes()) == []
    assert json.loads(dynamic_file.read_text(encoding="utf-8")) == {}
    with pytest.raises(RouteNotFoundError):
        asyncio.run(router.remove_route("gone"))


def test_get_route_not_found(traefik_file_pair: tuple[Path, TraefikFileTrafficRouter]) -> None:
    _, router = traefik_file_pair
    with pytest.raises(RouteNotFoundError):
        asyncio.run(router.get_route("missing"))


def test_invalid_host_for_rule(traefik_file_pair: tuple[Path, TraefikFileTrafficRouter]) -> None:
    _, router = traefik_file_pair
    with pytest.raises(RouteConfigurationError):
        asyncio.run(
            router.upsert_route(
                RouteSpec(
                    route_id="bad",
                    host="bad`host",
                    path_prefix="/",
                    backend_host="x",
                    backend_port=80,
                )
            )
        )
