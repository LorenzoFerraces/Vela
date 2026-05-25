"""Unified deploy source suggestions (images, GitHub repos, Dockerfile templates)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import user_library
from app.core.exceptions import ProviderConnectionError
from app.core.oauth import decrypt_identity_token, get_github_identity, list_user_repos
from app.core.oauth.github import GitHubRepo
from app.core.orchestrator import ContainerOrchestrator
from app.core.registry_image_suggestions import (
    fetch_docker_hub_suggestions,
    merge_image_suggestions,
)
from app.db.models import User, UserOAuthIdentity


class DeploySourceImageSuggestion(BaseModel):
    kind: Literal["image"] = "image"
    ref: str
    label: str


class DeploySourceGitSuggestion(BaseModel):
    kind: Literal["git"] = "git"
    url: str
    name: str
    default_branch: str


class DeploySourceDockerfileTemplateSuggestion(BaseModel):
    kind: Literal["dockerfile_template"] = "dockerfile_template"
    id: uuid.UUID
    name: str


DeploySourceSuggestion = (
    DeploySourceImageSuggestion
    | DeploySourceGitSuggestion
    | DeploySourceDockerfileTemplateSuggestion
)


class DeploySourcesResponse(BaseModel):
    suggestions: list[DeploySourceSuggestion] = Field(default_factory=list)


def _git_clone_url(html_url: str) -> str:
    trimmed = html_url.strip().rstrip("/")
    if trimmed.endswith(".git"):
        return trimmed
    return f"{trimmed}.git"


async def _load_local_image_tags(orchestrator: ContainerOrchestrator) -> list[str]:
    try:
        return await orchestrator.list_images()
    except ProviderConnectionError:
        return []


async def _load_docker_hub_rows(stripped: str, image_slots: int) -> list[tuple[str, int]]:
    if not stripped:
        return []
    return await fetch_docker_hub_suggestions(
        stripped,
        page_size=max(image_slots * 2, 20),
    )


async def _load_github_repos(
    identity: UserOAuthIdentity | None,
    *,
    stripped: str,
    git_slots: int,
) -> list[GitHubRepo]:
    if identity is None or not identity.access_token_encrypted:
        return []
    token = decrypt_identity_token(identity)
    try:
        return await list_user_repos(
            token,
            query=stripped or None,
            page=1,
            per_page=git_slots,
        )
    except Exception:
        return []


async def collect_deploy_source_suggestions(
    *,
    session: AsyncSession,
    user: User,
    orchestrator: ContainerOrchestrator,
    query: str,
    limit: int,
) -> DeploySourcesResponse:
    """Merge image, GitHub, and Dockerfile template hints for the deploy combobox."""
    bounded_limit = max(1, min(limit, 40))
    image_slots = max(bounded_limit // 2, 6)
    git_slots = max(bounded_limit // 4, 4)
    template_slots = max(
        bounded_limit - image_slots - git_slots,
        4,
    )

    stripped = query.strip()
    suggestions: list[DeploySourceSuggestion] = []

    local_tags_task = asyncio.create_task(_load_local_image_tags(orchestrator))
    hub_rows_task = asyncio.create_task(_load_docker_hub_rows(stripped, image_slots))

    templates = await user_library.list_dockerfile_templates_matching_name(
        session,
        user.id,
        stripped,
        limit=template_slots,
    )
    identity = await get_github_identity(session, user.id)
    repos_task = asyncio.create_task(
        _load_github_repos(
            identity,
            stripped=stripped,
            git_slots=git_slots,
        )
    )

    local_tags, hub_rows, repos = await asyncio.gather(
        local_tags_task,
        hub_rows_task,
        repos_task,
    )
    for item in merge_image_suggestions(
        query=stripped,
        limit=image_slots,
        local_tags=local_tags,
        hub_rows=hub_rows,
    ):
        suggestions.append(
            DeploySourceImageSuggestion(ref=item.ref, label=item.ref)
        )

    for row in templates:
        suggestions.append(
            DeploySourceDockerfileTemplateSuggestion(id=row.id, name=row.name)
        )

    for repo in repos:
        if not repo.html_url:
            continue
        suggestions.append(
            DeploySourceGitSuggestion(
                url=_git_clone_url(repo.html_url),
                name=repo.full_name or repo.html_url,
                default_branch=repo.default_branch or "main",
            )
        )

    return DeploySourcesResponse(suggestions=suggestions[:bounded_limit])
