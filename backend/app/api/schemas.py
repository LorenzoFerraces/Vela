"""HTTP request/response models (API layer)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.models import ContainerInfo, ProjectSource


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
        description=(
            "Port the application listens on inside the container. When host_port is set, "
            "Docker publishes host_port→this port. When host_port is omitted, Traefik still "
            "forwards to this port on the container network."
        ),
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


class ImageAvailabilityResponse(BaseModel):
    """Result of checking whether a registry image reference can be resolved."""

    ref: str = Field(..., description="Trimmed image reference that was checked.")
    available: bool = Field(
        ...,
        description="True when the image exists locally or the registry reports the manifest.",
    )
    checked: bool = Field(
        default=True,
        description="False for Git clone URLs; the client should not gate deploy on this result.",
    )
    detail: str | None = Field(
        default=None,
        description="Set when ``available`` is false or the check could not complete usefully.",
    )
    error_code: str | None = Field(
        default=None,
        description="Stable machine-readable code when the image is missing (e.g. ``image_not_found``).",
    )
    hints: list[str] | None = Field(
        default=None,
        description="Actionable suggestions when the image cannot be resolved.",
    )
    registry_detail: str | None = Field(
        default=None,
        description="Short message from Docker or the registry when available.",
    )
    can_attempt_deploy: bool = Field(
        default=True,
        description=(
            "When ``available`` is false: false means the reference is missing; true means the "
            "registry denied lookup (401/403) so deploy may still succeed after ``docker login``."
        ),
    )


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


class BuilderBuildRequest(BaseModel):
    """POST /api/builder/build body."""

    source: ProjectSource
    tag: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Image reference to assign to the built image (e.g. vela/myapp:dev).",
    )


class BuilderAnalyzeRequest(BaseModel):
    """POST /api/builder/analyze body (local directory on the server)."""

    project_path: str = Field(..., min_length=1, max_length=4096)


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


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserPublic(BaseModel):
    """User shape returned to the client (no password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserPublic
