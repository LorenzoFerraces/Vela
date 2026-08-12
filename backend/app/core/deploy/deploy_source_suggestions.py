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
from app.core.oauth.github import (
    GitHubRepo,
    find_accessible_repo_by_name,
    parse_github_repo_url,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.build.registry_image_suggestions import (
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
    pasted_github_hint: str | None = None


def _git_clone_url(html_url: str) -> str:
    """
    Normalize a Git repository HTML URL into a cloneable `.git` URL.
    
    Parameters:
        html_url (str): Repository HTML URL (may include surrounding whitespace or a trailing slash).
    
    Returns:
        str: A clone URL that ends with `.git`.
    """
    trimmed = html_url.strip().rstrip("/")
    if trimmed.endswith(".git"):
        return trimmed
    return f"{trimmed}.git"


async def _load_local_image_tags(orchestrator: ContainerOrchestrator) -> list[str]:
    """
    Load local container image tags from the provided orchestrator.
    
    If the orchestrator fails to respond due to a provider connection error, an empty list is returned.
    
    Returns:
        list[str]: Image tag strings discovered locally, or an empty list on connection failure.
    """
    try:
        return await orchestrator.list_images()
    except ProviderConnectionError:
        return []


async def _load_docker_hub_rows(stripped: str, image_slots: int) -> list[tuple[str, int]]:
    """
    Fetch Docker Hub suggestion rows for a given query.
    
    Parameters:
        stripped (str): The trimmed query string to search for; if empty, no lookup is performed.
        image_slots (int): Number of image suggestion slots used to determine the Docker Hub page size.
    
    Returns:
        list[tuple[str, int]]: A list of (image_reference, score) tuples returned by Docker Hub; returns an empty list when `stripped` is empty.
    """
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
    """
    Fetch GitHub repositories for the given user identity, optionally filtered by a query.
    
    Parameters:
        identity (UserOAuthIdentity | None): The user's GitHub OAuth identity; if None or missing an encrypted token, no request is made.
        stripped (str): Search string to filter repositories; empty string disables query filtering.
        git_slots (int): Maximum number of repositories to return (per-page request size).
    
    Returns:
        list[GitHubRepo]: Repositories matching the query for the authenticated user, or an empty list if the identity is missing/invalid or if an error occurs.
    """
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


async def _resolve_pasted_github_repo(
    identity: UserOAuthIdentity | None,
    query: str,
) -> tuple[DeploySourceGitSuggestion | None, str | None]:
    repo_ref = parse_github_repo_url(query)
    if repo_ref is None:
        return None, None
    if identity is None or not identity.access_token_encrypted:
        return None, "Connect GitHub in Settings to deploy private repositories."
    token = decrypt_identity_token(identity)
    preferred_owners = [repo_ref.owner]
    if identity.username:
        preferred_owners.append(identity.username)
    try:
        outcome = await find_accessible_repo_by_name(
            token,
            repo_name=repo_ref.repo,
            preferred_owners=preferred_owners,
        )
    except Exception:
        return None, None
    if outcome.repo is None or not outcome.repo.html_url:
        if outcome.org_sso_authorize_url:
            return (
                None,
                "Authorize Vela for your GitHub organization, then retry. "
                "Open GitHub → Settings → Applications → Vela → Configure SSO.",
            )
        return None, None
    return (
        DeploySourceGitSuggestion(
            url=_git_clone_url(outcome.repo.html_url),
            name=outcome.repo.full_name or f"{repo_ref.owner}/{repo_ref.repo}",
            default_branch=outcome.repo.default_branch or "main",
        ),
        None,
    )


async def collect_deploy_source_suggestions(
    *,
    session: AsyncSession,
    user: User,
    orchestrator: ContainerOrchestrator,
    query: str,
    limit: int,
) -> DeploySourcesResponse:
    """
    Collect and merge deploy-source suggestions for the UI deploy combobox.
    
    Builds a bounded, ordered list of suggestions from three sources—container images (local and Docker Hub), user Dockerfile templates, and GitHub repositories—by allocating per-source slot budgets based on `limit`, loading sources concurrently, and merging results into a single list ordered as: image suggestions, Dockerfile templates, then GitHub repos. The returned response contains at most the normalized limit of suggestions.
    
    Parameters:
        session (AsyncSession): Database session used for user and template lookups.
        user (User): The requesting user whose templates and GitHub identity are consulted.
        orchestrator (ContainerOrchestrator): Orchestrator used to enumerate local container image tags.
        query (str): User-typed query string used to filter suggestions.
        limit (int): Requested maximum number of suggestions; clamped to the range 1–40.
    
    Returns:
        DeploySourcesResponse: Response containing up to the clamped number of deploy-source suggestions, ordered with image suggestions first, then Dockerfile templates, then GitHub repository suggestions.
    """
    bounded_limit = max(1, min(limit, 40))
    image_slots = max(bounded_limit // 2, 6)
    git_slots = max(bounded_limit // 4, 4)
    template_slots = max(
        bounded_limit - image_slots - git_slots,
        4,
    )

    stripped = query.strip()
    pasted_repo_ref = parse_github_repo_url(stripped)
    if pasted_repo_ref is not None:
        git_slots = max(git_slots, 30)
    suggestions: list[DeploySourceSuggestion] = []

    github_search_query = (
        pasted_repo_ref.repo if pasted_repo_ref is not None else stripped
    )
    hub_search_query = "" if pasted_repo_ref is not None else stripped

    local_tags_task = asyncio.create_task(_load_local_image_tags(orchestrator))
    hub_rows_task = asyncio.create_task(_load_docker_hub_rows(hub_search_query, image_slots))

    templates = await user_library.list_dockerfile_templates_matching_name(
        session,
        user.id,
        stripped,
        limit=template_slots,
    )
    identity = await get_github_identity(session, user.id)
    pasted_repo_task = asyncio.create_task(
        _resolve_pasted_github_repo(identity, stripped)
    )
    repos_task = asyncio.create_task(
        _load_github_repos(
            identity,
            stripped=github_search_query,
            git_slots=git_slots,
        )
    )

    local_tags, hub_rows, repos, pasted_resolution = await asyncio.gather(
        local_tags_task,
        hub_rows_task,
        repos_task,
        pasted_repo_task,
    )
    pasted_repo, pasted_github_hint = pasted_resolution
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

    if pasted_repo is not None:
        suggestions = [
            row
            for row in suggestions
            if not (
                isinstance(row, DeploySourceGitSuggestion)
                and row.url == pasted_repo.url
            )
        ]
        suggestions.insert(0, pasted_repo)

    return DeploySourcesResponse(
        suggestions=suggestions[:bounded_limit],
        pasted_github_hint=pasted_github_hint,
    )
