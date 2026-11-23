from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PreviewSecretForbiddenError, SecretNotFoundError
from app.core.models import DeployConfig
from app.core.secret_store import parse_secret_reference, resolve_secret_reference


async def runtime_config_with_secrets(
    session: AsyncSession, config: DeployConfig, *, owner_user_id: uuid.UUID,
    project_id: uuid.UUID | None, allow_secrets: bool = True,
) -> DeployConfig:
    resolved: dict[str, str] = {}
    for key, value in config.env_vars.items():
        reference = parse_secret_reference(value)
        if reference is None:
            resolved[key] = value
            continue
        if not allow_secrets:
            raise PreviewSecretForbiddenError(f"Secret reference in env key {key!r} is not allowed for previews")
        name, version = reference
        try:
            resolved[key] = await resolve_secret_reference(
                session, owner_user_id=owner_user_id, project_id=project_id, name=name, version=version,
            )
        except SecretNotFoundError:
            # Deploys always pass a concrete project id, even for the personal
            # workspace; owner-scoped secrets live outside any project.
            if project_id is None:
                raise
            resolved[key] = await resolve_secret_reference(
                session, owner_user_id=owner_user_id, project_id=None, name=name, version=version,
            )
    return config.model_copy(update={"env_vars": resolved})
