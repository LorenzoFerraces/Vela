"""Allocate hostnames and build public URLs for Vela-managed Traefik routes."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException

from app.core.models import DeployConfig
from app.core.traffic_router import TrafficRouter

_MAX_ALLOCATION_ATTEMPTS = 64


def read_public_route_settings() -> tuple[str, str, str]:
    """Return ``(base_domain, url_scheme, label_prefix)`` from the environment."""
    domain = os.environ.get("VELA_PUBLIC_ROUTE_DOMAIN", "").strip().lower().strip(".")
    scheme_raw = os.environ.get("VELA_PUBLIC_URL_SCHEME", "https").strip().lower()
    if scheme_raw not in ("http", "https", ""):
        raise HTTPException(
            status_code=400,
            detail="VELA_PUBLIC_URL_SCHEME must be http or https.",
        )
    scheme = scheme_raw or "https"
    prefix = os.environ.get("VELA_PUBLIC_ROUTE_HOST_PREFIX", "vela-").strip()
    return domain, scheme, prefix


def read_public_route_settings_or_raise_for_public_deploy() -> tuple[str, str, str]:
    """Like :func:`read_public_route_settings` but requires a non-empty base domain."""
    domain, scheme, prefix = read_public_route_settings()
    if not domain:
        raise HTTPException(
            status_code=400,
            detail="public_route requires VELA_PUBLIC_ROUTE_DOMAIN to be set on the server.",
        )
    return domain, scheme, prefix


def build_public_url(*, scheme: str, host: str, path_prefix: str) -> str:
    """Return a canonical URL for the edge route (path_prefix must start with ``/``)."""
    path = path_prefix if path_prefix.startswith("/") else f"/{path_prefix}"
    if path == "/":
        return f"{scheme}://{host}/"
    return f"{scheme}://{host}{path}"


async def allocate_public_hostname(
    traffic_router: TrafficRouter,
    *,
    base_domain: str,
    label_prefix: str,
) -> str:
    """Pick a unique FQDN under ``base_domain`` not already present in the traffic router."""
    base_domain = base_domain.strip().lower().strip(".").strip()
    if not base_domain or ".." in base_domain or "/" in base_domain:
        raise HTTPException(
            status_code=500,
            detail="VELA_PUBLIC_ROUTE_DOMAIN is invalid.",
        )

    routes = await traffic_router.list_routes()
    occupied = {r.host.lower() for r in routes}

    prefix = label_prefix.strip()
    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        slug = secrets.token_hex(8)
        label = f"{prefix}{slug}" if prefix else slug
        label = label.strip("-")
        if not label or len(label) > 200:
            continue
        host = f"{label}.{base_domain}"
        if len(host) > 253:
            continue
        if host.lower() not in occupied:
            return host.lower()

    raise HTTPException(
        status_code=503,
        detail="Could not allocate a unique public route hostname; try again later.",
    )


async def apply_public_route_to_deploy_config(
    config: DeployConfig,
    traffic_router: TrafficRouter,
) -> DeployConfig:
    """If ``config.public_route`` is set, fill ``route_host`` / ``route_tls`` from env and allocation."""
    if not config.public_route:
        return config
    domain, scheme, prefix = read_public_route_settings_or_raise_for_public_deploy()
    host = await allocate_public_hostname(traffic_router, base_domain=domain, label_prefix=prefix)
    tls = scheme == "https"
    return config.model_copy(update={"route_host": host, "route_tls": tls})
