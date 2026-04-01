from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import (
    BuildStrategy,
    ContainerStatus,
    HealthStatus,
    RestartPolicy,
    SupportedLanguage,
)


# ---------------------------------------------------------------------------
# Orchestrator models
# ---------------------------------------------------------------------------


class PortMapping(BaseModel):
    host_port: int
    container_port: int
    protocol: str = "tcp"


class HealthCheckConfig(BaseModel):
    command: list[str]
    interval_s: int = 30
    timeout_s: int = 5
    retries: int = 3
    start_period_s: int = 0


class DeployConfig(BaseModel):
    image: str
    name: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    ports: list[PortMapping] = Field(default_factory=list)
    cpu_limit: float | None = None
    memory_limit: int | None = None
    restart_policy: RestartPolicy = RestartPolicy.NEVER
    labels: dict[str, str] = Field(default_factory=dict)
    command: list[str] | None = None
    health_check: HealthCheckConfig | None = None


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: ContainerStatus
    created_at: datetime
    ports: list[PortMapping] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    health: HealthStatus = HealthStatus.NONE


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
