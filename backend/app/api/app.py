"""FastAPI application factory."""

from __future__ import annotations

import app.bootstrap_env  # noqa: F401 — loads backend/.env before other app imports.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import auth, builder, containers, images, traffic

API_PREFIX = "/api"


def create_app() -> FastAPI:
    application = FastAPI(
        title="Vela API",
        description="Container deployment platform — orchestrate, build, and manage containers.",
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://velaunq.ddns.net:5173",
            "https://velaunq.ddns.net:5173",
        ],
        allow_origin_regex=r"^https?://[^/]+:5173$",
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
        traffic.router,
        prefix=API_PREFIX,
        tags=["traffic"],
    )
    application.include_router(
        auth.router,
        prefix=f"{API_PREFIX}/auth",
        tags=["auth"],
    )

    @application.get(f"{API_PREFIX}/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
