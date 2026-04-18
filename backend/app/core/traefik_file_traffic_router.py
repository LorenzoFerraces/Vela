"""Traefik file-provider integration: writes a dynamic JSON file plus local state."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.core.exceptions import RouteConfigurationError, RouteNotFoundError, TrafficRouterError
from app.core.traffic_models import RouteInfo, RouteSpec
from app.core.traffic_router import TrafficRouter

_STATE_SUFFIX = ".vela-traffic-state.json"
# Traefik object names are capped in practice; reserve room for TLS split suffixes.
_MAX_TRAEFIK_OBJECT_KEY_LEN = 200
_SUFFIX_ROUTER_PLAIN = "_w"  # cleartext edge (entrypoint ``web``)
_SUFFIX_ROUTER_TLS = "_ws"  # TLS edge (entrypoint ``websecure``)


def _traefik_safe_key(route_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", route_id).strip("_")
    if not safe:
        raise RouteConfigurationError("route_id must contain at least one alphanumeric character")
    key = f"vela_{safe}"
    return key[:200]


def _host_rule(host: str) -> str:
    if "`" in host or "\\" in host:
        raise RouteConfigurationError("host contains invalid characters")
    return f"Host(`{host}`)"


def _path_rule(path_prefix: str) -> str:
    escaped = path_prefix.replace("\\", "\\\\").replace("'", "\\'")
    return f"PathPrefix(`{escaped}`)"


def _build_rule(spec: RouteSpec) -> str:
    host_part = _host_rule(spec.host)
    if spec.path_prefix in ("/", ""):
        return host_part
    return f"{host_part} && {_path_rule(spec.path_prefix)}"


def _backend_url(spec: RouteSpec) -> str:
    if "`" in spec.backend_host or " " in spec.backend_host:
        raise RouteConfigurationError("backend_host contains invalid characters")
    return f"http://{spec.backend_host}:{spec.backend_port}"


def _tls_split_router_keys(route_id: str) -> tuple[str, str]:
    """Return ``(web_router_key, websecure_router_key)`` under Traefik key length limits."""
    base = _traefik_safe_key(route_id)
    reserve = max(len(_SUFFIX_ROUTER_PLAIN), len(_SUFFIX_ROUTER_TLS))
    if len(base) + reserve > _MAX_TRAEFIK_OBJECT_KEY_LEN:
        base = base[: _MAX_TRAEFIK_OBJECT_KEY_LEN - reserve]
    return base + _SUFFIX_ROUTER_PLAIN, base + _SUFFIX_ROUTER_TLS


def _build_traefik_document(route_specs: list[RouteSpec]) -> dict[str, object]:
    """Build Traefik v3 dynamic JSON.

    Empty ``routers`` / ``services`` objects must be omitted: Traefik's file decoder
    rejects empty maps as standalone elements (``routers cannot be a standalone element``).
    With no routes, emit ``{}`` so the file provider loads an empty configuration.
    """
    routers: dict[str, object] = {}
    services: dict[str, object] = {}
    for spec in route_specs:
        key = _traefik_safe_key(spec.route_id)
        service_name = f"{key}_svc"
        rule = _build_rule(spec)
        services[service_name] = {
            "loadBalancer": {"servers": [{"url": _backend_url(spec)}]}
        }
        if spec.tls_enabled:
            # Two routers so both http://host:80 and https://host:443 match the same backend.
            key_web, key_websecure = _tls_split_router_keys(spec.route_id)
            routers[key_web] = {
                "rule": rule,
                "service": service_name,
                "entryPoints": ["web"],
            }
            routers[key_websecure] = {
                "rule": rule,
                "service": service_name,
                "entryPoints": ["websecure"],
                "tls": {},
            }
        else:
            router: dict[str, object] = {
                "rule": rule,
                "service": service_name,
                "entryPoints": list(spec.entrypoints),
            }
            routers[key] = router
    http: dict[str, object] = {}
    if routers:
        http["routers"] = routers
    if services:
        http["services"] = services
    if not http:
        return {}
    return {"http": http}


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        os.replace(tmp_path, target)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


class TraefikFileTrafficRouter(TrafficRouter):
    """Persist routes to a Traefik v3-compatible dynamic JSON file and a sidecar state file."""

    def __init__(
        self,
        *,
        traefik_dynamic_file: Path,
    ) -> None:
        self._traefik_file = traefik_dynamic_file.resolve()
        self._state_file = self._traefik_file.parent / _STATE_SUFFIX
        self._lock = asyncio.Lock()

    def _load_state_unlocked(self) -> dict[str, RouteSpec]:
        if not self._state_file.is_file():
            return {}
        try:
            raw = self._state_file.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise TrafficRouterError(f"Failed to read traffic state: {exc}") from exc
        routes_raw = payload.get("routes")
        if not isinstance(routes_raw, list):
            return {}
        result: dict[str, RouteSpec] = {}
        for item in routes_raw:
            if isinstance(item, dict):
                try:
                    spec = RouteSpec.model_validate(item)
                except ValidationError:
                    continue
                result[spec.route_id] = spec
        return result

    def _save_state_and_traefik_unlocked(self, routes: dict[str, RouteSpec]) -> None:
        specs = list(routes.values())
        state_payload = {
            "routes": [spec.model_dump(mode="json") for spec in specs],
        }
        traefik_doc = _build_traefik_document(specs)
        try:
            state_bytes = json.dumps(
                state_payload,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            traefik_bytes = json.dumps(traefik_doc, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            _atomic_write_bytes(self._state_file, state_bytes)
            _atomic_write_bytes(self._traefik_file, traefik_bytes)
        except OSError as exc:
            raise TrafficRouterError(f"Failed to write Traefik dynamic file: {exc}") from exc

    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        async with self._lock:
            routes = await asyncio.to_thread(self._load_state_unlocked)
            routes[spec.route_id] = spec.model_copy(deep=True)
            await asyncio.to_thread(self._save_state_and_traefik_unlocked, routes)
        return RouteInfo.from_spec(spec)

    async def remove_route(self, route_id: str) -> None:
        async with self._lock:
            routes = await asyncio.to_thread(self._load_state_unlocked)
            if route_id not in routes:
                raise RouteNotFoundError(route_id)
            del routes[route_id]
            await asyncio.to_thread(self._save_state_and_traefik_unlocked, routes)

    async def get_route(self, route_id: str) -> RouteInfo:
        async with self._lock:
            routes = await asyncio.to_thread(self._load_state_unlocked)
        spec = routes.get(route_id)
        if spec is None:
            raise RouteNotFoundError(route_id)
        return RouteInfo.from_spec(spec)

    async def list_routes(self) -> list[RouteInfo]:
        async with self._lock:
            routes = await asyncio.to_thread(self._load_state_unlocked)
        return [RouteInfo.from_spec(spec) for spec in routes.values()]
