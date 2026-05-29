"""HTTP request/response models (API layer)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.models import ContainerInfo, ProjectSource


class RunFromSourceRequest(BaseModel):
    """Run a container from a registry image, Git URL, or saved Dockerfile template."""

    source_kind: Literal["image", "git", "dockerfile_template"] | None = Field(
        default=None,
        description="Explicit deploy source; when omitted, ``source`` is inferred.",
    )
    source: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Legacy: image ref or Git URL (used when ``source_kind`` is omitted).",
    )
    image_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Registry image when ``source_kind`` is ``image``.",
    )
    git_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Git clone URL when ``source_kind`` is ``git``.",
    )
    dockerfile_template_id: uuid.UUID | None = Field(
        default=None,
        description="Saved Dockerfile template when ``source_kind`` is ``dockerfile_template``.",
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
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables injected into the container at start.",
    )
    command: list[str] | None = Field(
        default=None,
        description="Optional command override (Docker CMD) when starting the container.",
    )

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, value: dict[str, str]) -> dict[str, str]:
        validated: dict[str, str] = {}
        original_keys_by_trimmed: dict[str, str] = {}
        for key, env_value in value.items():
            trimmed_key = key.strip()
            if not trimmed_key:
                msg = "Environment variable keys cannot be empty."
                raise ValueError(msg)
            if len(trimmed_key) > 256:
                msg = "Environment variable keys cannot exceed 256 characters."
                raise ValueError(msg)
            if trimmed_key in original_keys_by_trimmed:
                prior_key = original_keys_by_trimmed[trimmed_key]
                msg = (
                    f"Duplicate environment variable keys after trimming: "
                    f"{prior_key!r} and {key!r} both map to {trimmed_key!r}."
                )
                raise ValueError(msg)
            original_keys_by_trimmed[trimmed_key] = key
            validated[trimmed_key] = env_value
        return validated

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        tokens = [token.strip() for token in value if token.strip()]
        if not tokens:
            msg = "command must contain at least one non-empty token when provided."
            raise ValueError(msg)
        return tokens

    @field_validator("route_path_prefix")
    @classmethod
    def route_path_prefix_must_start_with_slash(cls, value: str) -> str:
        """
        Validate that a Traefik route path prefix begins with a leading '/'.
        
        Parameters:
            value (str): The route path prefix to validate.
        
        Returns:
            str: The validated route path prefix (returned unchanged) if it starts with '/'.
        
        Raises:
            ValueError: If `value` does not start with '/'.
        """
        if not value.startswith("/"):
            msg = "route_path_prefix must start with '/'"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_source_fields(self) -> RunFromSourceRequest:
        """
        Validate and normalize the request's source fields and enforce mode-specific requirements.
        
        If `source_kind` is omitted, infer the kind from the legacy `source` value and return a copy with `source_kind` set and the appropriate field (`git_url` or `image_ref`) populated with the trimmed legacy value. If `source_kind` is `"image"` or `"git"`, ensure the respective field (`image_ref` or `git_url`) is present (or fall back to `source`), trim it, and return a copy with that field set. If `source_kind` is `"dockerfile_template"`, ensure `dockerfile_template_id` is provided.
        
        Returns:
            RunFromSourceRequest: A validated and possibly normalized copy of the request model.
        
        Raises:
            ValueError: When a required source field is missing or empty for the selected deployment kind.
        """
        kind = self.source_kind
        if kind is None:
            legacy = (self.source or "").strip()
            if not legacy:
                raise ValueError("source is required when source_kind is omitted.")
            if legacy.startswith(("git@", "http://", "https://", "ssh://")):
                return self.model_copy(
                    update={"source_kind": "git", "git_url": legacy},
                )
            return self.model_copy(
                update={"source_kind": "image", "image_ref": legacy},
            )
        if kind == "image":
            ref = (self.image_ref or self.source or "").strip()
            if not ref:
                raise ValueError("image_ref or source is required for image deploy.")
            return self.model_copy(update={"image_ref": ref})
        if kind == "git":
            url = (self.git_url or self.source or "").strip()
            if not url:
                raise ValueError("git_url or source is required for git deploy.")
            return self.model_copy(update={"git_url": url})
        if self.dockerfile_template_id is None:
            raise ValueError(
                "dockerfile_template_id is required for dockerfile_template deploy."
            )
        return self


class ImageSuggestion(BaseModel):
    """One autocomplete candidate for a registry image reference."""

    ref: str = Field(..., description="Suggested image reference (may omit implicit :latest).")
    pull_count: int | None = Field(
        default=None,
        description="Docker Hub pull count when ``source`` is ``registry`` and Hub returned it.",
    )
    source: Literal["local", "registry"] = Field(
        ...,
        description="Whether the hint came from the local engine or Docker Hub search.",
    )


class ImageSuggestionsResponse(BaseModel):
    """Merged image autocomplete list (local tags + Hub, ordered for the UI)."""

    suggestions: list[ImageSuggestion]


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
    kind: Literal["image", "git", "dockerfile_template"]
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
# Git source analysis (Gemini pre-fill)
# ---------------------------------------------------------------------------


class AnalyzeGitSourceRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=2048)
    git_branch: str = Field(default="main", max_length=256)


class GitSourceAnalysis(BaseModel):
    git_branch: str | None = None
    container_port: int = Field(default=80, ge=1, le=65535)
    container_name: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    start_command: list[str] | None = None
    language: str | None = None
    framework: str | None = None
    has_dockerfile: bool = False
    build_strategy: Literal["dockerfile_exists", "generated_dockerfile"] = (
        "generated_dockerfile"
    )
    summary_hint: str = ""


class AiPrefillPreferences(BaseModel):
    git_branch: bool = True
    container_port: bool = True
    container_name: bool = True
    env_vars: bool = True
    start_command: bool = True


class AiPrefillPreferencesUpdate(BaseModel):
    git_branch: bool | None = None
    container_port: bool | None = None
    container_name: bool | None = None
    env_vars: bool | None = None
    start_command: bool | None = None


class GeminiConfigStatus(BaseModel):
    configured: bool


# ---------------------------------------------------------------------------
# Deployment history
# ---------------------------------------------------------------------------


class DeploymentRecordPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    author_email: str
    container_id: str
    container_name: str | None
    source_kind: Literal["image", "git", "dockerfile_template"]
    source_ref: str
    git_branch: str | None
    image_tag: str
    container_port: int
    env_vars: dict[str, str]
    command: list[str] | None
    dockerfile_snapshot: str | None
    public_url: str | None
    created_at: datetime


class DeploymentEnvDiff(BaseModel):
    added: dict[str, str] = Field(default_factory=dict)
    removed: dict[str, str] = Field(default_factory=dict)
    changed: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Keys map to {before, after} env values.",
    )


class DeploymentDiffResponse(BaseModel):
    left_id: uuid.UUID
    right_id: uuid.UUID
    env: DeploymentEnvDiff
    dockerfile_diff: list[str]


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


# ---------------------------------------------------------------------------
# GitHub OAuth schemas
# ---------------------------------------------------------------------------


class GitHubAuthorizeUrlResponse(BaseModel):
    authorize_url: str = Field(
        ..., description="GitHub authorize URL the SPA navigates to."
    )


class GitHubStatusResponse(BaseModel):
    connected: bool
    login: str | None = None
    avatar_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None


class GitHubRepoSummary(BaseModel):
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    description: str | None = None


class GitHubBranchSummary(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# User library (Dockerfile templates)
# ---------------------------------------------------------------------------


class DockerfileTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    contents: str = Field(..., min_length=1)


class DockerfileTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contents: str | None = Field(default=None, min_length=1)


class DockerfileTemplatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contents: str
    created_at: datetime
    updated_at: datetime
