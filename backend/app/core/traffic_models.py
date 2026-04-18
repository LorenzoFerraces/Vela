"""Provider-agnostic models for HTTP edge routing (ingress intent)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RouteSpec(BaseModel):
    """Desired HTTP route from hostname/path to a backend reachable by the edge proxy."""

    route_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier used in config keys and API paths.",
    )
    host: str = Field(
        ...,
        min_length=1,
        max_length=253,
        description="Public hostname for the route (e.g. app.example.com).",
    )
    path_prefix: str = Field(
        default="/",
        max_length=512,
        description="URL path prefix; use '/' for all paths on this host.",
    )
    backend_host: str = Field(
        ...,
        min_length=1,
        max_length=253,
        description="Hostname or container name the proxy resolves (Docker network DNS, etc.).",
    )
    backend_port: int = Field(..., ge=1, le=65535)
    tls_enabled: bool = Field(
        default=False,
        description="If true, the generated Traefik router references TLS (entrypoints must match static config).",
    )
    entrypoints: list[str] = Field(
        default_factory=lambda: ["web"],
        description="Traefik entry point names (e.g. web, websecure).",
    )

    @field_validator("path_prefix")
    @classmethod
    def path_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "path_prefix must start with '/'"
            raise ValueError(msg)
        return value

    @field_validator("entrypoints")
    @classmethod
    def entrypoints_non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            msg = "entrypoints must contain at least one entry point name"
            raise ValueError(msg)
        return value


class RouteInfo(BaseModel):
    """Route as stored or exposed by the control plane."""

    route_id: str
    host: str
    path_prefix: str
    backend_host: str
    backend_port: int
    tls_enabled: bool
    entrypoints: list[str]

    @classmethod
    def from_spec(cls, spec: RouteSpec) -> RouteInfo:
        return cls(
            route_id=spec.route_id,
            host=spec.host,
            path_prefix=spec.path_prefix,
            backend_host=spec.backend_host,
            backend_port=spec.backend_port,
            tls_enabled=spec.tls_enabled,
            entrypoints=list(spec.entrypoints),
        )
