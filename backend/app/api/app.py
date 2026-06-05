"""FastAPI application factory."""

from __future__ import annotations

import app.bootstrap_env  # noqa: F401 — loads backend/.env before other app imports.

import asyncio
from contextlib import asynccontextmanager

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
    settings,
    traffic,
)

API_PREFIX = "/api"


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    """
    Lifespan context manager that ensures the end-to-end test database is prepared before the application starts.
    
    This async context manager runs once at startup to await e2e database setup, starts the container monitoring loop, then yields control for the application runtime. On shutdown, the monitoring task is cancelled.
    """
    from app.e2e_support import ensure_e2e_database
    from app.core.notifications.container_monitor import run_monitoring_loop

    await ensure_e2e_database()

    monitor_task = asyncio.create_task(run_monitoring_loop())

    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


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

    @application.get(f"{API_PREFIX}/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
