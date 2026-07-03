"""FastAPI application factory."""

from __future__ import annotations

import app.bootstrap_env  # noqa: F401 — loads backend/.env before other app imports.

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import (
    auth,
    builder,
    containers,
    deployments,
    dockerfile_templates,
    github,
    images,
    projects,
    scaling,
    settings,
    traffic,
    users,
)

API_PREFIX = "/api"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    """Startup/shutdown lifecycle: initialise DB, start background monitoring and scaling loops."""
    from app.api.deps import get_orchestrator, get_traffic_router
    from app.core.exceptions import ProviderConnectionError
    from app.core.notifications.container_monitor import run_monitoring_loop
    from app.core.scaling.scaling_engine import run_scaling_loop
    from app.e2e_support import ensure_e2e_database

    await ensure_e2e_database()

    monitor_task = asyncio.create_task(run_monitoring_loop())
    scaling_task: asyncio.Task[None] | None = None
    try:
        orchestrator = get_orchestrator()
        traffic_router = get_traffic_router()
    except ProviderConnectionError:
        logger.warning("Docker unavailable at startup; auto-scaling loop will not run.")
    else:
        scaling_task = asyncio.create_task(
            run_scaling_loop(orchestrator, traffic_router)
        )

    try:
        yield
    finally:
        monitor_task.cancel()
        if scaling_task is not None:
            scaling_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        if scaling_task is not None:
            with suppress(asyncio.CancelledError):
                await scaling_task


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application used by the service.

    The returned application is configured with a custom startup/shutdown lifespan, CORS middleware, global exception handlers, mounted API routers under the `/api` prefix (containers, builder, images, dockerfiles, traffic, auth, github, settings, deployments), and a health endpoint at `/api/health`.

    Returns:
        FastAPI: A configured FastAPI application instance.
    """
    application = FastAPI(
        title="Vela API",
        description="Container deployment platform — orchestrate, build, and manage containers.",
        version="0.1.0",
        lifespan=_lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://velaunq.ddns.net:5173",
            "https://velaunq.ddns.net:5173",
        ],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)

    application.include_router(
        containers.router,
        prefix=f"{API_PREFIX}/containers",
        tags=["containers"],
    )
    application.include_router(
        builder.router,
        prefix=f"{API_PREFIX}/builder",
        tags=["builder"],
    )
    application.include_router(
        images.router,
        prefix=f"{API_PREFIX}/images",
        tags=["images"],
    )
    application.include_router(
        dockerfile_templates.router,
        prefix=f"{API_PREFIX}/dockerfiles",
        tags=["dockerfiles"],
    )
    application.include_router(
        traffic.router,
        prefix=API_PREFIX,
        tags=["traffic"],
    )
    application.include_router(
        auth.router,
        prefix=f"{API_PREFIX}/auth",
        tags=["auth"],
    )
    application.include_router(
        users.router,
        prefix=f"{API_PREFIX}/users",
        tags=["users"],
    )
    application.include_router(
        github.router_auth,
        prefix=f"{API_PREFIX}/auth",
        tags=["github"],
    )
    application.include_router(
        github.router_resource,
        prefix=f"{API_PREFIX}/github",
        tags=["github"],
    )
    application.include_router(
        settings.router,
        prefix=f"{API_PREFIX}/settings",
        tags=["settings"],
    )
    application.include_router(
        deployments.router,
        prefix=f"{API_PREFIX}/deployments",
        tags=["deployments"],
    )
    application.include_router(
        projects.router,
        prefix=f"{API_PREFIX}/projects",
        tags=["projects"],
    )
    application.include_router(
        scaling.router,
        prefix=f"{API_PREFIX}/scaling",
        tags=["scaling"],
    )

    @application.get(f"{API_PREFIX}/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
