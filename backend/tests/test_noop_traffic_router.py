"""Tests for NoopTrafficRouter."""

from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import RouteNotFoundError
from app.core.traffic_models import RouteSpec
from app.core.traffic_router import NoopTrafficRouter


def test_noop_upsert_list_remove() -> None:
    router = NoopTrafficRouter()
    spec = RouteSpec(
        route_id="a",
        host="h.test",
        path_prefix="/",
        backend_host="svc",
        backend_port=80,
    )
    asyncio.run(router.upsert_route(spec))
    assert len(asyncio.run(router.list_routes())) == 1
    asyncio.run(router.remove_route("a"))
    assert asyncio.run(router.list_routes()) == []
    with pytest.raises(RouteNotFoundError):
        asyncio.run(router.get_route("a"))
