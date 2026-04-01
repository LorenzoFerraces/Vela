from enum import StrEnum


class ContainerStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    RESTARTING = "restarting"
    STOPPED = "stopped"
    DEAD = "dead"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    NONE = "none"


class RestartPolicy(StrEnum):
    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"
    UNLESS_STOPPED = "unless_stopped"


class BuildStrategy(StrEnum):
    DOCKERFILE_EXISTS = "dockerfile_exists"
    GENERATED_DOCKERFILE = "generated_dockerfile"
    BUILDPACK = "buildpack"


class SupportedLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    JAVA = "java"
    RUST = "rust"
    RUBY = "ruby"
    UNKNOWN = "unknown"
