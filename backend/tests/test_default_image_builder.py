"""Tests for :class:`~app.core.default_image_builder.DefaultImageBuilder`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.core.default_image_builder import DefaultImageBuilder
from app.core.enums import BuildStrategy
from app.core.models import ProjectSource
from app.core.orchestrator import ContainerOrchestrator


def _fake_orchestrator() -> MagicMock:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.build_image = AsyncMock(return_value="sha256:deadbeef")
    return orch


def test_build_from_local_generates_dockerfile_and_builds(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"start":"node a.js"}}', encoding="utf-8")
    orch = _fake_orchestrator()
    builder = DefaultImageBuilder(orch)

    result = asyncio.run(
        builder.build_from_source(ProjectSource(local_path=str(tmp_path)), tag="vela/t:1")
    )

    assert result.strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert result.image_tag == "vela/t:1"
    assert (tmp_path / "Dockerfile").is_file()
    orch.build_image.assert_awaited_once()
    call_kw = orch.build_image.await_args
    assert call_kw.kwargs["tag"] == "vela/t:1"
    assert call_kw.kwargs["dockerfile"] == "Dockerfile"
