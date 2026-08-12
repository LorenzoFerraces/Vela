"""DefaultImageBuilder must honor build_subdir and BuildOverride."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import BuildStrategy, SupportedLanguage
from app.core.exceptions import AnalysisError
from app.core.models import BuildOverride, BuildResult, ProjectInfo, ProjectSource
from app.core.stacks import deploy as stack_deploy


class RecordingOrchestrator(FakeContainerOrchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.build_paths: list[str] = []

    async def build_image(
        self, path: str, *, tag: str, dockerfile: str = "Dockerfile"
    ) -> str:
        self.build_paths.append(path)
        return await super().build_image(path, tag=tag, dockerfile=dockerfile)


@pytest.mark.asyncio
async def test_nested_marker_builds_from_subdir(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "requirements.txt").write_text("flask\n", encoding="utf-8")

    orchestrator = RecordingOrchestrator()
    builder = DefaultImageBuilder(orchestrator=orchestrator)

    result = await builder.build_from_source(
        ProjectSource(local_path=str(tmp_path)),
        tag="test:nested",
    )

    assert result.project_info.build_subdir == "backend"
    assert len(orchestrator.build_paths) == 1
    assert Path(orchestrator.build_paths[0]).resolve() == backend.resolve()
    assert (backend / "Dockerfile").is_file()


@pytest.mark.asyncio
async def test_override_build_subdir_used_as_context(tmp_path: Path) -> None:
    apps = tmp_path / "apps" / "api"
    apps.mkdir(parents=True)
    (apps / "requirements.txt").write_text("flask\n", encoding="utf-8")

    orchestrator = RecordingOrchestrator()
    builder = DefaultImageBuilder(orchestrator=orchestrator)

    await builder.build_from_source(
        ProjectSource(local_path=str(tmp_path)),
        tag="test:override-subdir",
        override=BuildOverride(
            language=SupportedLanguage.PYTHON,
            build_subdir="apps/api",
        ),
    )

    assert Path(orchestrator.build_paths[0]).resolve() == apps.resolve()


@pytest.mark.asyncio
async def test_invalid_build_subdir_rejected(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
    builder = DefaultImageBuilder(orchestrator=FakeContainerOrchestrator())

    with pytest.raises(AnalysisError, match="build_subdir"):
        await builder.build_from_source(
            ProjectSource(local_path=str(tmp_path)),
            tag="test:bad-subdir",
            override=BuildOverride(
                language=SupportedLanguage.PYTHON,
                build_subdir="../outside",
            ),
        )


@pytest.mark.asyncio
async def test_resolve_service_image_passes_build_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_build_from_source(
        source: ProjectSource,
        *,
        tag: str,
        access_token: str | None = None,
        override: BuildOverride | None = None,
    ) -> BuildResult:
        captured["override"] = override
        captured["source"] = source
        captured["access_token"] = access_token
        return BuildResult(
            image_id="sha256:fake",
            image_tag=tag,
            strategy=BuildStrategy.GENERATED_DOCKERFILE,
            build_log="",
            project_info=ProjectInfo(language=SupportedLanguage.PYTHON),
        )

    async def fake_github_token(_session: object, _user: object, _url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.api.routes.containers._github_token_for_url",
        fake_github_token,
    )

    builder = MagicMock()
    builder.build_from_source = AsyncMock(side_effect=fake_build_from_source)
    session = AsyncMock()
    user = SimpleNamespace(id="user-1")
    service = SimpleNamespace(
        source_kind="git",
        source_ref="https://github.com/example/repo.git",
        git_branch="develop",
        build_override={
            "language": "python",
            "build_subdir": "backend",
            "language_version": "3.12",
        },
    )

    tag = await stack_deploy._resolve_service_image(session, user, builder, service)

    assert tag.startswith("vela/gitbuild:")
    override = captured["override"]
    assert isinstance(override, BuildOverride)
    assert override.language is SupportedLanguage.PYTHON
    assert override.build_subdir == "backend"
    assert override.language_version == "3.12"
    source = captured["source"]
    assert isinstance(source, ProjectSource)
    assert source.git_url == "https://github.com/example/repo.git"
    assert source.branch == "develop"
