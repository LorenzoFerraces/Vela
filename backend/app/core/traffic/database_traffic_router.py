from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import RouteNotFoundError
from app.core.traffic.traffic_models import BackendServer, RouteInfo, RouteSpec
from app.core.traffic.traefik_file_traffic_router import (
    _atomic_write_bytes,
    _build_traefik_document,
    _reload_traefik_container_sighup,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import TrafficRouteRecord


class DatabaseTrafficRouter(TrafficRouter):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        traefik_dynamic_file: Path,
        reload_container: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.traefik_dynamic_file = traefik_dynamic_file.resolve()
        self._reload_container = reload_container
        self._lock = asyncio.Lock()

    async def _all_specs(self, session: AsyncSession) -> list[RouteSpec]:
        rows = (await session.execute(select(TrafficRouteRecord))).scalars().all()
        return [
            RouteSpec(
                route_id=row.route_id,
                host=row.host,
                path_prefix=row.path_prefix,
                backend_servers=[
                    BackendServer.model_validate(item) for item in row.backend_servers
                ],
                tls_enabled=row.tls_enabled,
                entrypoints=row.entrypoints,
            )
            for row in rows
        ]

    async def _write_document(self, specs: list[RouteSpec]) -> None:
        document = _build_traefik_document(specs)
        await asyncio.to_thread(
            _atomic_write_bytes,
            self.traefik_dynamic_file,
            json.dumps(document, indent=2, sort_keys=True).encode("utf-8"),
        )
        if self._reload_container:
            _reload_traefik_container_sighup(self._reload_container)

    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        async with self._lock:
            async with self._session_factory() as session:
                record = await session.get(TrafficRouteRecord, spec.route_id)
                if record is None:
                    session.add(
                        TrafficRouteRecord(
                            route_id=spec.route_id,
                            host=spec.host,
                            path_prefix=spec.path_prefix,
                            backend_servers=[
                                server.model_dump() for server in spec.backend_servers
                            ],
                            tls_enabled=spec.tls_enabled,
                            entrypoints=spec.entrypoints,
                        )
                    )
                else:
                    record.host, record.path_prefix = spec.host, spec.path_prefix
                    record.backend_servers = [
                        server.model_dump() for server in spec.backend_servers
                    ]
                    record.tls_enabled = spec.tls_enabled
                    record.entrypoints = spec.entrypoints
                await session.commit()
                await self._write_document(await self._all_specs(session))
        return RouteInfo.from_spec(spec)

    async def remove_route(self, route_id: str) -> None:
        async with self._lock:
            async with self._session_factory() as session:
                record = await session.get(TrafficRouteRecord, route_id)
                if record is None:
                    raise RouteNotFoundError(f"Route {route_id} not found")
                await session.delete(record)
                await session.commit()
                await self._write_document(await self._all_specs(session))

    async def get_route(self, route_id: str) -> RouteInfo:
        async with self._session_factory() as session:
            record = await session.get(TrafficRouteRecord, route_id)
            if record is None:
                raise RouteNotFoundError(f"Route {route_id} not found")
            spec = RouteSpec(
                route_id=record.route_id,
                host=record.host,
                path_prefix=record.path_prefix,
                backend_servers=[
                    BackendServer.model_validate(item) for item in record.backend_servers
                ],
                tls_enabled=record.tls_enabled,
                entrypoints=record.entrypoints,
            )
            return RouteInfo.from_spec(spec)

    async def list_routes(self) -> list[RouteInfo]:
        async with self._session_factory() as session:
            return [RouteInfo.from_spec(spec) for spec in await self._all_specs(session)]
