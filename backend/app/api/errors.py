"""Map domain exceptions to HTTP responses."""

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AnalysisError,
    AuthError,
    AvatarValidationError,
    BuilderError,
    CloneError,
    GitSourceAnalysisError,
    UnsupportedProjectError,
    ContainerAlreadyRunningError,
    ContainerNotFoundError,
    ContainerNotRunningError,
    DockerfileGenerationError,
    DockerfileTemplateNotFoundError,
    DuplicateDockerfileNameError,
    EmailAlreadyRegisteredError,
    GitHubAccountAlreadyLinkedError,
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubOAuthError,
    ImageBuildError,
    ImageNotFoundError,
    IntegrationConfigurationError,
    IntegrationError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    ObjectStorageError,
    AlreadyProjectMemberError,
    DuplicateInvitationError,
    InvitationAlreadyRespondedError,
    InvitationNotFoundError,
    ProjectAccessDeniedError,
    ProjectError,
    ProjectMemberNotFoundError,
    ProjectNotFoundError,
    UserNotRegisteredError,
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


def _project_error_payload(exc: ProjectError, error_code: str) -> dict[str, str]:
    return {"error": error_code, "detail": str(exc)}


def register_exception_handlers(app) -> None:
    """
    Register exception handlers on a FastAPI application that translate Vela domain errors into JSON HTTP responses.

    Each installed handler maps a VelaError subclass (and related exceptions) to an appropriate HTTP status code and JSON response body (for some exceptions the handler uses the exception's api_response_content()). The registered handlers also add authentication headers where applicable.

    Parameters:
        app (FastAPI): The FastAPI application on which to register the exception handlers.
    """

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

    @app.exception_handler(ProjectNotFoundError)
    @app.exception_handler(ProjectMemberNotFoundError)
    @app.exception_handler(InvitationNotFoundError)
    async def project_not_found_handler(
        _request: Request, exc: ProjectError
    ) -> JSONResponse:
        codes = {
            ProjectNotFoundError: "project_not_found",
            ProjectMemberNotFoundError: "project_member_not_found",
            InvitationNotFoundError: "invitation_not_found",
        }
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_project_error_payload(exc, codes[type(exc)]),
        )

    @app.exception_handler(ProjectAccessDeniedError)
    async def project_access_denied_handler(
        _request: Request, exc: ProjectAccessDeniedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=_project_error_payload(exc, "project_access_denied"),
        )

    @app.exception_handler(UserNotRegisteredError)
    async def user_not_registered_handler(
        _request: Request, exc: UserNotRegisteredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_project_error_payload(exc, "user_not_registered"),
        )

    @app.exception_handler(AlreadyProjectMemberError)
    @app.exception_handler(DuplicateInvitationError)
    @app.exception_handler(InvitationAlreadyRespondedError)
    async def project_conflict_handler(
        _request: Request, exc: ProjectError
    ) -> JSONResponse:
        codes = {
            AlreadyProjectMemberError: "already_project_member",
            DuplicateInvitationError: "duplicate_invitation",
            InvitationAlreadyRespondedError: "invitation_already_responded",
        }
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_project_error_payload(exc, codes[type(exc)]),
        )

    @app.exception_handler(RouteNotFoundError)
    @app.exception_handler(ContainerNotFoundError)
    @app.exception_handler(DockerfileTemplateNotFoundError)
    async def not_found_handler(_request: Request, exc: VelaError) -> JSONResponse:
        """
        Produce a 404 Not Found JSON response for the given domain error.

        Parameters:
            _request (Request): The incoming HTTP request (unused).
            exc (VelaError): The domain error to convert into the response.

        Returns:
            JSONResponse: Response with HTTP 404 and body `{"detail": str(exc)}`.
        """
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ContainerAlreadyRunningError)
    @app.exception_handler(ContainerNotRunningError)
    @app.exception_handler(DuplicateDockerfileNameError)
    async def conflict_handler(_request: Request, exc: VelaError) -> JSONResponse:
        """
        Map a domain conflict error to an HTTP 409 Conflict JSON response.

        Parameters:
            _request (Request): Incoming request (unused).
            exc (VelaError): Domain-layer error whose message will be placed in the response `detail`.

        Returns:
            JSONResponse: Response with status code 409 and body `{"detail": str(exc)}`.
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ResourceLimitError)
    @app.exception_handler(AvatarValidationError)
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

    @app.exception_handler(GitHubAccountAlreadyLinkedError)
    async def github_account_already_linked_handler(
        _request: Request, exc: GitHubAccountAlreadyLinkedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "code": "github_account_already_linked"},
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

    @app.exception_handler(ObjectStorageError)
    async def object_storage_handler(
        _request: Request, exc: ObjectStorageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(GitSourceAnalysisError)
    async def git_source_analysis_handler(
        _request: Request, exc: GitSourceAnalysisError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
