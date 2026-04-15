"""Map domain exceptions to HTTP responses."""

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AnalysisError,
    BuilderError,
    CloneError,
    ContainerAlreadyRunningError,
    ContainerNotFoundError,
    ContainerNotRunningError,
    DockerfileGenerationError,
    ImageBuildError,
    ImageNotFoundError,
    OrchestratorError,
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

    @app.exception_handler(RouteNotFoundError)
    @app.exception_handler(ContainerNotFoundError)
    @app.exception_handler(ImageNotFoundError)
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
    async def builder_subclass_handler(_request: Request, exc: BuilderError) -> JSONResponse:
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
    async def traffic_router_handler(_request: Request, exc: TrafficRouterError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @app.exception_handler(OrchestratorError)
    async def orchestrator_handler(_request: Request, exc: OrchestratorError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(exc)},
        )

    @app.exception_handler(VelaError)
    async def vela_handler(_request: Request, exc: VelaError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(exc)},
        )
