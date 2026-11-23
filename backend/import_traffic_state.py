from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.traffic.traefik_file_traffic_router import (
    _atomic_write_bytes,
    _build_traefik_document,
)
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.db.engine import get_session_factory
from app.db.models import TrafficRouteRecord


async def import_traffic_state(
    file_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    dynamic_file: Path,
) -> int:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    specs = [RouteSpec.model_validate(item) for item in payload["routes"]]
    async with session_factory() as session:
        for spec in specs:
            existing = await session.get(TrafficRouteRecord, spec.route_id)
            if existing is None:
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
        await session.commit()
        rows = (await session.execute(select(TrafficRouteRecord))).scalars().all()
    document = _build_traefik_document(
        [
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
    )
    await asyncio.to_thread(
        _atomic_write_bytes,
        dynamic_file,
        json.dumps(document, indent=2, sort_keys=True).encode("utf-8"),
    )
    return len(specs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--dynamic-file", required=True, type=Path)
    args = parser.parse_args()
    count = asyncio.run(
        import_traffic_state(args.file, get_session_factory(), args.dynamic_file)
    )
    print(f"Imported {count} routes")


if __name__ == "__main__":
    main()
