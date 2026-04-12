"""HTTP request/response models (API layer)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class RunFromSourceResponse(BaseModel):
    container: ContainerInfo
    kind: Literal["image", "git"]
    image: str
