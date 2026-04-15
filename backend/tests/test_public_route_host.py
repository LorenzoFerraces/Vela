"""Tests for public route hostname allocation and URL building."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.core.models import DeployConfig
from app.core.public_route_host import (
    apply_public_route_to_deploy_config,
    build_public_url,
    read_public_route_settings,
)
from app.core.traffic_router import NoopTrafficRouter


def test_build_public_url_root_and_path() -> None:
    assert build_public_url(scheme="https", host="h.example.com", path_prefix="/") == "https://h.example.com/"
    assert build_public_url(scheme="http", host="h.example.com", path_prefix="/api") == "http://h.example.com/api"


def test_read_public_route_settings_invalid_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "ftp")
    with pytest.raises(HTTPException) as exc:
        read_public_route_settings()
    assert exc.value.status_code == 400


def test_apply_public_route_allocates_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_HOST_PREFIX", "t-")
    router = NoopTrafficRouter()
    cfg = DeployConfig(image="nginx:alpine", public_route=True)

    async def run() -> None:
        out = await apply_public_route_to_deploy_config(cfg, router)
        assert out.route_host.endswith(".apps.example.com")
        assert out.route_host.startswith("t-")
        assert out.route_tls is True

    asyncio.run(run())


def test_apply_public_route_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "run.dev")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "http")
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_HOST_PREFIX", "")
    router = NoopTrafficRouter()
    cfg = DeployConfig(image="nginx:alpine", public_route=True)

    async def run() -> None:
        out = await apply_public_route_to_deploy_config(cfg, router)
        assert out.route_host.endswith(".run.dev")
        assert out.route_tls is False

    asyncio.run(run())


def test_apply_public_route_requires_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_PUBLIC_ROUTE_DOMAIN", raising=False)
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "")
    router = NoopTrafficRouter()
    cfg = DeployConfig(image="nginx:alpine", public_route=True)

    async def run() -> None:
        await apply_public_route_to_deploy_config(cfg, router)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 400


def test_apply_skips_when_public_route_false() -> None:
    router = NoopTrafficRouter()
    cfg = DeployConfig(
        image="nginx:alpine",
        public_route=False,
        route_host="manual.test",
        route_tls=True,
    )

    async def run() -> None:
        out = await apply_public_route_to_deploy_config(cfg, router)
        assert out is cfg

    asyncio.run(run())
