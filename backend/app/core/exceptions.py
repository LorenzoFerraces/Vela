class VelaError(Exception):
    """Base exception for all Vela errors."""


# ---------------------------------------------------------------------------
# Orchestrator errors
# ---------------------------------------------------------------------------


class OrchestratorError(VelaError):
    """Base exception for container orchestration failures."""


class ContainerNotFoundError(OrchestratorError):
    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        super().__init__(f"Container not found: {container_id}")


class ImageNotFoundError(OrchestratorError):
    def __init__(self, image: str) -> None:
        self.image = image
        super().__init__(f"Image not found: {image}")


class ContainerAlreadyRunningError(OrchestratorError):
    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        super().__init__(f"Container is already running: {container_id}")


class ContainerNotRunningError(OrchestratorError):
    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        super().__init__(f"Container is not running: {container_id}")


class ImageBuildError(OrchestratorError):
    def __init__(self, message: str, build_log: str = "") -> None:
        self.build_log = build_log
        super().__init__(message)


class ResourceLimitError(OrchestratorError):
    pass


class ProviderConnectionError(OrchestratorError):
    """Cannot reach the container runtime (Docker daemon, k8s API, etc.)."""


# ---------------------------------------------------------------------------
# Builder errors
# ---------------------------------------------------------------------------


class BuilderError(VelaError):
    """Base exception for image-building failures."""


class UnsupportedLanguageError(BuilderError):
    def __init__(self, language: str) -> None:
        self.language = language
        super().__init__(
            f"No Dockerfile template available for language: {language}"
        )


class CloneError(BuilderError):
    def __init__(self, git_url: str, message: str) -> None:
        self.git_url = git_url
        super().__init__(f"Failed to clone {git_url}: {message}")


class AnalysisError(BuilderError):
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"Project analysis failed for {path}: {message}")


class DockerfileGenerationError(BuilderError):
    def __init__(self, language: str, message: str) -> None:
        self.language = language
        super().__init__(
            f"Dockerfile generation failed for {language}: {message}"
        )
