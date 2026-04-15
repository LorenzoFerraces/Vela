"""HTTP request/response models (API layer)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.models import ContainerInfo


class RunFromSourceRequest(BaseModel):
    """Run a container from a registry image or from a Git URL (Docker build)."""

    source: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Docker image reference (e.g. nginx:alpine) or Git clone URL.",
    )
    container_name: str | None = Field(
        default=None,
        max_length=128,
        description="Optional Docker container name.",
    )
    host_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="If set, publish this host port to container_port (TCP).",
    )
    container_port: int = Field(
        default=80,
        ge=1,
        le=65535,
        description="Container port to expose when host_port is set.",
    )
    git_branch: str = Field(
        default="main",
        max_length=256,
        description="Branch to clone when source is a Git URL.",
    )
    route_host: str | None = Field(
        default=None,
        max_length=253,
        description="If set, register a Traefik route for this hostname after the container starts.",
    )
    route_path_prefix: str = Field(
        default="/",
        max_length=512,
        description="URL path prefix for the Traefik route.",
    )
    route_tls: bool = Field(
        default=False,
        description="Enable TLS on the generated Traefik router (matches static entrypoints).",
    )
    public_route: bool = Field(
        default=False,
        description=(
            "If true, server allocates a hostname under VELA_PUBLIC_ROUTE_DOMAIN; "
            "route_host from this request is ignored."
        ),
    )

    @field_validator("route_path_prefix")
    @classmethod
    def route_path_prefix_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "route_path_prefix must start with '/'"
            raise ValueError(msg)
        return value


class RunFromSourceResponse(BaseModel):
    container: ContainerInfo
    kind: Literal["image", "git"]
    image: str
    route_wired: bool = Field(
        default=False,
        description="True if a Traefik route was registered for this deploy.",
    )
    public_url: str | None = Field(
        default=None,
        description="Canonical URL when public_route was used and the route was wired.",
    )


class ContainerDeployResponse(BaseModel):
    """Result of POST /containers/deploy with optional edge route metadata."""

    container: ContainerInfo
    route_wired: bool = Field(
        default=False,
        description="True if a Traefik route was registered for this deploy.",
    )
    public_url: str | None = Field(
        default=None,
        description="Canonical URL when public_route was used and the route was wired.",
    )
