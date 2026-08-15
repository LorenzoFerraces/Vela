"""Third-party OAuth integrations (currently GitHub OAuth Apps)."""

from app.core.oauth.clerk import (
    ClerkClaims,
    reset_jwks_cache_for_tests,
    verify_clerk_token,
)
from app.core.oauth.github import (
    GitHubOAuthConfig,
    GitHubProfile,
    GitHubRepo,
    GitHubRepoRef,
    exchange_code_for_token,
    fetch_github_user,
    fetch_user_repo_if_accessible,
    list_repo_branches,
    list_user_repos,
    load_config,
    parse_github_repo_url,
    revoke_user_grant,
)
from app.core.oauth.github import build_authorize_url
from app.core.oauth.identity import (
    CLERK_PROVIDER,
    GITHUB_PROVIDER,
    decrypt_identity_token,
    delete_github_identity,
    get_clerk_identity,
    get_clerk_identity_by_subject,
    get_github_identity,
    upsert_clerk_identity,
    upsert_github_identity,
)
from app.core.oauth.state import (
    decode_state,
    encode_state,
)

__all__ = [
    "CLERK_PROVIDER",
    "ClerkClaims",
    "GitHubOAuthConfig",
    "GitHubProfile",
    "GitHubRepo",
    "GITHUB_PROVIDER",
    "GitHubRepoRef",
    "build_authorize_url",
    "decode_state",
    "decrypt_identity_token",
    "delete_github_identity",
    "encode_state",
    "exchange_code_for_token",
    "fetch_github_user",
    "get_clerk_identity",
    "get_clerk_identity_by_subject",
    "fetch_user_repo_if_accessible",
    "get_github_identity",
    "list_repo_branches",
    "list_user_repos",
    "load_config",
    "reset_jwks_cache_for_tests",
    "parse_github_repo_url",
    "revoke_user_grant",
    "upsert_clerk_identity",
    "upsert_github_identity",
    "verify_clerk_token",
]
