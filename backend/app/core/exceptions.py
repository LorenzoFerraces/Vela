from app.core.image_not_found_payload import image_not_found_api_content
from app.core.registry_access_payload import registry_access_denied_api_content


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
    """Raised when an image reference cannot be resolved locally or on a registry."""

    def __init__(self, image: str, *, registry_message: str | None = None) -> None:
        self.image = image
        self.registry_message = registry_message
        self._api_content = image_not_found_api_content(
            image, registry_detail=registry_message
        )
        super().__init__(str(self._api_content["detail"]))

    def api_response_content(self) -> dict[str, object]:
        """Structured fields for JSON error responses (404)."""
        return dict(self._api_content)


class RegistryAccessDeniedError(OrchestratorError):
    """Raised when the registry returns 401/403 for a manifest or pull (auth / rate limit / policy)."""

    def __init__(self, image: str, *, registry_message: str | None = None) -> None:
        self.image = image
        self.registry_message = registry_message
        self._api_content = registry_access_denied_api_content(
            image, registry_detail=registry_message
        )
        super().__init__(str(self._api_content["detail"]))

    def api_response_content(self) -> dict[str, object]:
        """Structured fields for JSON error responses (403)."""
        return dict(self._api_content)


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
        super().__init__(f"No Dockerfile template available for language: {language}")


class UnsupportedProjectError(VelaError):
    """No Dockerfile and no recognized project markers (e.g. package.json)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


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
        super().__init__(f"Dockerfile generation failed for {language}: {message}")


# ---------------------------------------------------------------------------
# Traffic / edge routing errors
# ---------------------------------------------------------------------------


class TrafficRouterError(VelaError):
    """Edge HTTP routing failures (misconfiguration, I/O, unsupported backend)."""


class RouteNotFoundError(VelaError):
    def __init__(self, route_id: str) -> None:
        self.route_id = route_id
        super().__init__(f"Route not found: {route_id}")


class RouteConfigurationError(VelaError):
    """Invalid route specification (client-facing)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------


class AuthError(VelaError):
    """Base exception for authentication failures."""


class EmailAlreadyRegisteredError(AuthError):
    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__("That email is already registered.")


class InvalidCredentialsError(AuthError):
    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class NotAuthenticatedError(AuthError):
    def __init__(self, message: str = "Not authenticated.") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Third-party integrations (GitHub OAuth)
# ---------------------------------------------------------------------------


class IntegrationError(VelaError):
    """Base exception for third-party integration failures (OAuth providers, etc.)."""


class IntegrationConfigurationError(IntegrationError):
    """The server is missing configuration required to talk to a provider."""


class GitHubNotConnectedError(IntegrationError):
    def __init__(
        self, message: str = "Connect your GitHub account in Settings first."
    ) -> None:
        super().__init__(message)


class GitHubOAuthError(IntegrationError):
    """Failure during the GitHub OAuth handshake (bad code, denied, expired state, ...)."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or f"GitHub authorization failed ({reason}).")


class GitHubAPIError(IntegrationError):
    """A call to the GitHub REST API failed."""

    def __init__(self, message: str = "GitHub request failed.") -> None:
        super().__init__(message)
