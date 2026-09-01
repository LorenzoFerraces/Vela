"""Tests for bind-mount extraction from Docker inspect data."""

from __future__ import annotations

from app.core.containers.docker_orchestrator import _volumes_from_inspect


def test_volumes_from_inspect_collects_bind_mounts_only() -> None:
    data = {
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/host/uploads/abc",
                "Destination": "/app/data",
            },
            {
                "Type": "volume",
                "Source": "named-volume",
                "Destination": "/var/lib/data",
            },
        ]
    }
    volumes = _volumes_from_inspect(data)
    assert len(volumes) == 1
    assert volumes[0].source == "/host/uploads/abc"
    assert volumes[0].target == "/app/data"
