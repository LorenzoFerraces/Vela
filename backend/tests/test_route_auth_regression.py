"""Every non-public /api route must reject an anonymous request."""
from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import builder, images, traffic

PUBLIC_PATHS = {
    "/api/health",
    "/api/runtime-config",
    "/api/auth/config",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/clerk/exchange",
    "/api/auth/github/start",
    "/api/auth/github/callback",
}


def test_every_non_public_api_route_requires_auth(
    anonymous_client: TestClient, integration_app: FastAPI
) -> None:
    for router in (traffic.router, images.router, builder.router):
        assert router.dependencies, f"{router.prefix or router} has no router-level auth"

    checked = 0
    api_paths = integration_app.openapi()["paths"]
    for path, path_item in api_paths.items():
        if not path.startswith("/api") or path in PUBLIC_PATHS:
            continue
        for method in path_item:
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            resolved = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
            response = anonymous_client.request(method.upper(), resolved)
            assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"
            checked += 1
    assert checked > 20
