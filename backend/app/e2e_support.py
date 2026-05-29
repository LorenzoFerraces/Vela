"""Bootstrap helpers when ``VELA_E2E=1`` (Playwright and local E2E runs)."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth.passwords import hash_password
from app.core.oauth.github import GitHubRepo
from app.core.oauth.identity import GITHUB_PROVIDER
from app.core.security.secrets import encrypt_secret
from app.db.base import Base
from app.db.engine import get_engine
from app.db.models import User, UserOAuthIdentity

if TYPE_CHECKING:
    from app.api.schemas import GitSourceAnalysis

E2E_USER_EMAIL = "e2e@example.com"
E2E_USER_PASSWORD = "e2e-test-password-min-8"
E2E_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
E2E_USER_NO_GITHUB_EMAIL = "e2e-nogithub@example.com"
E2E_USER_NO_GITHUB_PASSWORD = "e2e-nogithub-password-min-8"
E2E_USER_NO_GITHUB_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
E2E_GITHUB_FAKE_TOKEN = "e2e-fake-github-token"

_E2E_GITHUB_REPOS = (
    GitHubRepo(
        full_name="org/repo",
        default_branch="main",
        private=False,
        html_url="https://github.com/org/repo",
        description="E2E fixture repo",
    ),
)


def e2e_mode_enabled() -> bool:
    """
    Check whether end-to-end (E2E) mode is enabled via environment.

    Returns:
        bool: `True` if the VELA_E2E environment variable, after trimming whitespace, equals "1", `False` otherwise.
    """
    return os.environ.get("VELA_E2E", "").strip() == "1"


def _assert_e2e_db_reset_allowed() -> None:
    if os.environ.get("VELA_E2E_ALLOW_DB_RESET", "").strip() != "1":
        msg = (
            "Refusing E2E database reset: set VELA_E2E_ALLOW_DB_RESET=1 to opt in."
        )
        raise RuntimeError(msg)

    database_url = os.environ.get("VELA_DATABASE_URL", "").strip().lower()
    if not database_url:
        msg = "Refusing E2E database reset: VELA_DATABASE_URL is not set."
        raise RuntimeError(msg)

    safe_markers = (".e2e", "e2e-", "/e2e", "test", "sqlite")
    if not any(marker in database_url for marker in safe_markers):
        msg = (
            "Refusing E2E database reset: VELA_DATABASE_URL does not look like "
            "a local or test database."
        )
        raise RuntimeError(msg)


def e2e_github_repos_if_enabled(
    access_token: str,
    *,
    query: str | None,
    page: int,
    per_page: int,
) -> list[GitHubRepo] | None:
    """
    Return fixture GitHub repositories when E2E mode is enabled and the provided access token matches the fixture token.

    Parameters:
        access_token (str): The GitHub access token to validate against the E2E fixture token.
        query (str | None): Optional search string; trimmed and matched case-insensitively against repo full name and html_url.
        page (int): Ignored in E2E mode (present for API compatibility).
        per_page (int): Ignored in E2E mode (present for API compatibility).

    Returns:
        list[GitHubRepo] | None: A list of fixture `GitHubRepo` objects filtered by `query` when E2E mode is enabled and the token matches;
        an empty list if E2E mode is enabled but the token does not match; `None` if E2E mode is not enabled.
    """
    _ = page, per_page
    if not e2e_mode_enabled():
        return None
    if access_token != E2E_GITHUB_FAKE_TOKEN:
        return []
    cleaned = (query or "").strip().lower()
    repos = list(_E2E_GITHUB_REPOS)
    if cleaned:
        repos = [
            repo
            for repo in repos
            if cleaned in repo.full_name.lower()
            or cleaned in repo.html_url.lower()
        ]
    return repos


def e2e_git_source_analysis_if_enabled(
    git_url: str,
    git_branch: str,
) -> GitSourceAnalysis | None:
    from app.api.schemas import GitSourceAnalysis

    if not e2e_mode_enabled():
        return None
    _ = git_url
    branch = (git_branch or "main").strip() or "main"
    return GitSourceAnalysis(
        git_branch=branch,
        container_port=5173,
        container_name="repo",
        env_vars={"NODE_ENV": "development"},
        start_command=None,
        language="typescript",
        framework="vite",
        has_dockerfile=False,
        build_strategy="generated_dockerfile",
        summary_hint="E2E fixture: Vite dev server on port 5173.",
    )


async def ensure_e2e_database() -> None:
    """
    Prepare the database schema and idempotently seed E2E users and a GitHub OAuth identity when E2E mode is enabled.

    If E2E mode is not enabled, the function returns immediately. When enabled, it creates any missing tables, ensures a primary E2E user and a second user without GitHub identity exist (inserting them only if absent), and ensures a GitHub OAuth identity record exists for the primary E2E user. All inserts are committed as they are performed to make the operation safe to run repeatedly.
    """
    if not e2e_mode_enabled():
        return

    _assert_e2e_db_reset_allowed()

    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        existing = await session.get(User, E2E_USER_ID)
        if existing is None:
            session.add(
                User(
                    id=E2E_USER_ID,
                    email=E2E_USER_EMAIL,
                    password_hash=hash_password(E2E_USER_PASSWORD),
                )
            )
            await session.commit()

        no_github = await session.get(User, E2E_USER_NO_GITHUB_ID)
        if no_github is None:
            session.add(
                User(
                    id=E2E_USER_NO_GITHUB_ID,
                    email=E2E_USER_NO_GITHUB_EMAIL,
                    password_hash=hash_password(E2E_USER_NO_GITHUB_PASSWORD),
                )
            )
            await session.commit()

        identity_result = await session.execute(
            select(UserOAuthIdentity).where(
                UserOAuthIdentity.user_id == E2E_USER_ID,
                UserOAuthIdentity.provider == GITHUB_PROVIDER,
            )
        )
        if identity_result.scalar_one_or_none() is None:
            session.add(
                UserOAuthIdentity(
                    user_id=E2E_USER_ID,
                    provider=GITHUB_PROVIDER,
                    provider_subject="999",
                    username="vela-user",
                    avatar_url="https://avatars.example.com/u/1",
                    scopes="repo,read:user",
                    access_token_encrypted=encrypt_secret(E2E_GITHUB_FAKE_TOKEN),
                )
            )
            await session.commit()
