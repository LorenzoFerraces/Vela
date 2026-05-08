"""Third-party OAuth integrations (currently GitHub OAuth Apps)."""

from app.core.oauth.github import (
    GitHubOAuthConfig,
    GitHubProfile,
    GitHubRepo,
    exchange_code_for_token,
    fetch_github_user,
    list_repo_branches,
    list_user_repos,
    load_config,
    revoke_user_grant,
)
from app.core.oauth.github import build_authorize_url
from app.core.oauth.identity import (
    GITHUB_PROVIDER,
    decrypt_identity_token,
    delete_github_identity,
    get_github_identity,
    upsert_github_identity,
)
from app.core.oauth.state import (
    decode_state,
    encode_state,
)

__all__ = [
    "GITHUB_PROVIDER",
    "GitHubOAuthConfig",
    "GitHubProfile",
    "GitHubRepo",
    "build_authorize_url",
    "decode_state",
    "decrypt_identity_token",
    "delete_github_identity",
    "encode_state",
    "exchange_code_for_token",
    "fetch_github_user",
    "get_github_identity",
    "list_repo_branches",
    "list_user_repos",
    "load_config",
    "revoke_user_grant",
    "upsert_github_identity",
]
