from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import (
    BuildStrategy,
    ContainerStatus,
    EscalationPolicy,
    HealthStatus,
    RestartPolicy,
    ScalingMetric,
    SupportedLanguage,
)


# ---------------------------------------------------------------------------
# Orchestrator models
# ---------------------------------------------------------------------------


class PortMapping(BaseModel):
    host_port: int
    container_port: int
    protocol: str = "tcp"


class VolumeMount(BaseModel):
    source: str
    target: str

    @field_validator("source")
    @classmethod
    def source_must_be_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            msg = "Volume source cannot be empty."
            raise ValueError(msg)
        return trimmed

    @field_validator("target")
    @classmethod
    def target_must_be_absolute_path(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed.startswith("/"):
            msg = "Volume target must be an absolute path starting with '/'."
            raise ValueError(msg)
        return trimmed


class HealthCheckConfig(BaseModel):
    command: list[str]
    interval_s: int = 30
    timeout_s: int = 5
    retries: int = 3
    start_period_s: int = 0


def default_listen_port_health_check(listen_port: int) -> HealthCheckConfig:
    """Verify the configured port accepts TCP connections inside the container."""
    python_probe = (
        "import socket; "
        f"socket.create_connection(('127.0.0.1', {listen_port}), timeout=1).close()"
    )
    return HealthCheckConfig(
        command=[
            "CMD-SHELL",
            (
                f'python3 -c "{python_probe}" 2>/dev/null || '
                f'python -c "{python_probe}" 2>/dev/null || '
                f"nc -z 127.0.0.1 {listen_port} 2>/dev/null || "
                f"nc -z localhost {listen_port} 2>/dev/null || "
                f"bash -c 'exec 3<>/dev/tcp/127.0.0.1/{listen_port}' 2>/dev/null || "
                "exit 1"
            ),
        ],
        interval_s=15,
        timeout_s=5,
        retries=3,
        start_period_s=30,
    )


class DeployConfig(BaseModel):
    image: str
    name: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    ports: list[PortMapping] = Field(default_factory=list)
    volumes: list[VolumeMount] = Field(default_factory=list)
    container_listen_port: int = Field(
        default=80,
        ge=1,
        le=65535,
        description=(
            "TCP port the app listens on inside the container. Used as the Traefik backend "
            "target when ``ports`` is empty; if host ports are published, the first mapping's "
            "``container_port`` is used instead."
        ),
    )
    cpu_limit: float | None = None
    memory_limit: int | None = None
    escalation_policy: EscalationPolicy = EscalationPolicy.NONE
    restart_policy: RestartPolicy = RestartPolicy.NEVER
    labels: dict[str, str] = Field(default_factory=dict)
    command: list[str] | None = None
    health_check: HealthCheckConfig | None = None
    route_host: str | None = Field(
        default=None,
        description="If set, register a Traefik file-provider route to this host after deploy.",
    )
    route_path_prefix: str = Field(
        default="/",
        description="Path prefix for the edge route (ignored by the Docker engine).",
    )
    route_tls: bool = Field(
        default=False,
        description="Whether the generated Traefik router enables TLS (entrypoints must match).",
    )
    public_route: bool = Field(
        default=False,
        description=(
            "If true, allocate route_host under VELA_PUBLIC_ROUTE_DOMAIN and set route_tls from "
            "VELA_PUBLIC_URL_SCHEME; client-supplied route_host is ignored."
        ),
    )
    project_id: uuid.UUID | None = Field(
        default=None,
        description="Target project for the deployment; defaults to the caller's personal workspace.",
    )

    @field_validator("route_path_prefix")
    @classmethod
    def route_path_prefix_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "route_path_prefix must start with '/'"
            raise ValueError(msg)
        return value


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: ContainerStatus
    created_at: datetime
    ports: list[PortMapping] = Field(default_factory=list)
    volumes: list[VolumeMount] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    health: HealthStatus = HealthStatus.NONE
    access_url: str | None = Field(
        default=None,
        description="HTTPS or HTTP URL for the Traefik edge route when route labels are present.",
    )
    source_kind: str | None = Field(
        default=None,
        description="Deploy source kind from vela.source_kind label (image, git, dockerfile_template).",
    )
    source_label: str | None = Field(
        default=None,
        description="User-facing deploy source from vela.source_ref (template name, image ref, Git URL).",
    )
    access_role: str | None = Field(
        default=None,
        description="Caller's role for this container's project (owner, operator, viewer).",
    )


class ContainerStats(BaseModel):
    container_id: str
    timestamp: datetime
    cpu_percent: float
    memory_usage_bytes: int
    memory_limit_bytes: int
    memory_percent: float
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0


class HealthResult(BaseModel):
    status: HealthStatus
    timestamp: datetime
    output: str | None = None
    exit_code: int | None = None


# ---------------------------------------------------------------------------
# Builder models
# ---------------------------------------------------------------------------


class ProjectSource(BaseModel):
    git_url: str | None = None
    local_path: str | None = None
    branch: str = "main"

    @model_validator(mode="after")
    def exactly_one_source(self) -> ProjectSource:
        gu = (self.git_url or "").strip() or None
        lp = (self.local_path or "").strip() or None
        if (gu is None) == (lp is None):
            raise ValueError("Set exactly one of git_url or local_path")
        self.git_url = gu
        self.local_path = lp
        return self


class ProjectInfo(BaseModel):
    language: SupportedLanguage
    language_version: str | None = None
    framework: str | None = None
    entrypoint: str | None = None
    dependency_file: str | None = None
    has_dockerfile: bool = False
    dockerfile_path: str | None = None


class BuildResult(BaseModel):
    image_id: str
    image_tag: str
    strategy: BuildStrategy
    build_log: str
    project_info: ProjectInfo
    dockerfile_snapshot: str | None = None


# ---------------------------------------------------------------------------
# Scaling policy models
# ---------------------------------------------------------------------------


class ScalingPolicyConfig(BaseModel):
    """Desired auto-scaling configuration attached to a container service."""

    enabled: bool = True
    min_replicas: int = Field(default=1, ge=1, le=20)
    max_replicas: int = Field(default=3, ge=1, le=20)
    metric: ScalingMetric = ScalingMetric.CPU_PERCENT
    scale_up_threshold: float = Field(
        default=70.0,
        ge=0.0,
        description="Metric value above which the engine scales up.",
    )
    scale_down_threshold: float = Field(
        default=30.0,
        ge=0.0,
        description="Metric value below which the engine scales down.",
    )
    cooldown_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Minimum seconds between consecutive scaling actions.",
    )
    scale_up_stabilization_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description=(
            "Metric must stay at or above scale_up_threshold for this many seconds "
            "before a scale-up is applied."
        ),
    )
    scale_down_stabilization_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description=(
            "Metric must stay at or below scale_down_threshold for this many seconds "
            "before a scale-down is applied."
        ),
    )

    @field_validator("max_replicas")
    @classmethod
    def max_must_be_gte_min(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        min_replicas = data.get("min_replicas", 1)
        if value < min_replicas:
            msg = "max_replicas must be >= min_replicas"
            raise ValueError(msg)
        return value

    @field_validator("scale_up_threshold", "scale_down_threshold")
    @classmethod
    def threshold_within_metric_range(cls, value: float, info: object) -> float:
        data = getattr(info, "data", {})
        metric = data.get("metric", ScalingMetric.CPU_PERCENT)
        if metric == ScalingMetric.CPU_PERCENT and value > 100.0:
            msg = "CPU percent thresholds must be <= 100"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def thresholds_must_be_ordered(self) -> ScalingPolicyConfig:
        if self.scale_down_threshold >= self.scale_up_threshold:
            msg = "scale_down_threshold must be < scale_up_threshold"
            raise ValueError(msg)
        return self


class ScalingPolicyInfo(BaseModel):
    """Scaling policy as returned by the API (includes server-assigned fields)."""

    id: uuid.UUID
    container_name: str
    enabled: bool
    min_replicas: int
    max_replicas: int
    metric: ScalingMetric
    scale_up_threshold: float
    scale_down_threshold: float
    cooldown_seconds: int
    scale_up_stabilization_seconds: int
    scale_down_stabilization_seconds: int
    last_scaled_at: datetime | None
    created_at: datetime
    updated_at: datetime
