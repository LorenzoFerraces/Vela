"""Map domain exceptions to HTTP responses."""

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AnalysisError,
    AuthError,
    BuilderError,
    CloneError,
    UnsupportedProjectError,
    ContainerAlreadyRunningError,
    ContainerNotFoundError,
    ContainerNotRunningError,
    DockerfileGenerationError,
    EmailAlreadyRegisteredError,
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubOAuthError,
    ImageBuildError,
    ImageNotFoundError,
    IntegrationConfigurationError,
    IntegrationError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    OrchestratorError,
    RegistryAccessDeniedError,
    ProviderConnectionError,
    ResourceLimitError,
    RouteConfigurationError,
    RouteNotFoundError,
    TrafficRouterError,
    UnsupportedLanguageError,
    VelaError,
)


def register_exception_handlers(app) -> None:
    """Register handlers for Vela domain errors."""

    @app.exception_handler(ImageNotFoundError)
    async def image_not_found_handler(
        _request: Request, exc: ImageNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=exc.api_response_content(),
        )

    @app.exception_handler(RegistryAccessDeniedError)
    async def registry_access_denied_handler(
        _request: Request, exc: RegistryAccessDeniedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=exc.api_response_content(),
        )

    @app.exception_handler(RouteNotFoundError)
    @app.exception_handler(ContainerNotFoundError)
    async def not_found_handler(_request: Request, exc: VelaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ContainerAlreadyRunningError)
    @app.exception_handler(ContainerNotRunningError)
    async def conflict_handler(_request: Request, exc: VelaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ResourceLimitError)
    async def bad_request_handler(_request: Request, exc: VelaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    @app.exception_handler(UnsupportedProjectError)
    async def unsupported_project_handler(
        _request: Request, exc: UnsupportedProjectError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    @app.exception_handler(RouteConfigurationError)
    @app.exception_handler(ImageBuildError)
    async def image_build_handler(_request: Request, exc: VelaError) -> JSONResponse:
        payload: dict = {"detail": str(exc)}
        if isinstance(exc, ImageBuildError):
            payload["build_log"] = exc.build_log or None
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=payload,
        )

    @app.exception_handler(ProviderConnectionError)
    async def provider_connection_handler(
        _request: Request, exc: VelaError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @app.exception_handler(UnsupportedLanguageError)
    @app.exception_handler(CloneError)
    @app.exception_handler(AnalysisError)
    @app.exception_handler(DockerfileGenerationError)
    async def builder_subclass_handler(
        _request: Request, exc: BuilderError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(BuilderError)
    async def builder_handler(_request: Request, exc: BuilderError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(TrafficRouterError)
    async def traffic_router_handler(
        _request: Request, exc: TrafficRouterError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @app.exception_handler(OrchestratorError)
    async def orchestrator_handler(
        _request: Request, exc: OrchestratorError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(exc)},
        )

    @app.exception_handler(EmailAlreadyRegisteredError)
    async def email_already_registered_handler(
        _request: Request, exc: EmailAlreadyRegisteredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(InvalidCredentialsError)
    @app.exception_handler(NotAuthenticatedError)
    async def auth_unauthorized_handler(
        _request: Request, exc: AuthError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(AuthError)
    async def auth_handler(_request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(GitHubNotConnectedError)
    async def github_not_connected_handler(
        _request: Request, exc: GitHubNotConnectedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "code": "github_not_connected"},
        )

    @app.exception_handler(GitHubOAuthError)
    async def github_oauth_handler(
        _request: Request, exc: GitHubOAuthError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "reason": exc.reason},
        )

    @app.exception_handler(GitHubAPIError)
    async def github_api_handler(
        _request: Request, exc: GitHubAPIError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(IntegrationConfigurationError)
    async def integration_config_handler(
        _request: Request, exc: IntegrationConfigurationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @app.exception_handler(IntegrationError)
    async def integration_handler(
        _request: Request, exc: IntegrationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(VelaError)
    async def vela_handler(_request: Request, exc: VelaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(exc)},
        )
