"""GitHub OAuth App client (authorize URL, token exchange, REST helpers).

Only this module talks to GitHub directly so token-handling code lives in one
place. All HTTP goes through ``httpx.AsyncClient``; the access token is never
logged or returned to callers verbatim except by the higher-level service that
encrypts it for storage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.exceptions import GitHubAPIError, GitHubOAuthError, IntegrationConfigurationError

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - public endpoint, not a secret
_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)
_DEFAULT_SCOPES = "repo,read:user"
_USER_AGENT = "vela-backend"


@dataclass(frozen=True)
class GitHubOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str


@dataclass(frozen=True)
class GitHubProfile:
    id: int
    login: str
    avatar_url: str | None


@dataclass(frozen=True)
class GitHubRepo:
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    description: str | None


def load_config() -> GitHubOAuthConfig:
    """Read the GitHub OAuth App config from env, raising a clear error if missing."""
    client_id = os.environ.get("VELA_GITHUB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("VELA_GITHUB_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("VELA_GITHUB_OAUTH_REDIRECT_URI", "").strip()
    scopes = os.environ.get("VELA_GITHUB_OAUTH_SCOPES", "").strip() or _DEFAULT_SCOPES

    missing = [
        name
        for name, value in (
            ("VELA_GITHUB_CLIENT_ID", client_id),
            ("VELA_GITHUB_CLIENT_SECRET", client_secret),
            ("VELA_GITHUB_OAUTH_REDIRECT_URI", redirect_uri),
        )
        if not value
    ]
    if missing:
        raise IntegrationConfigurationError(
            "GitHub OAuth is not configured. Set "
            + ", ".join(missing)
            + " in backend/.env."
        )
    return GitHubOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )


def build_authorize_url(config: GitHubOAuthConfig, *, state: str) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scopes.replace(",", " "),
        "state": state,
        "allow_signup": "false",
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    config: GitHubOAuthConfig,
    *,
    code: str,
    state: str,
) -> tuple[str, str]:
    """Exchange an authorization ``code`` for ``(access_token, granted_scopes)``."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            response = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                    "state": state,
                },
                headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            )
        except httpx.HTTPError as exc:
            raise GitHubOAuthError("network_error", "Could not reach GitHub.") from exc

    if response.status_code != httpx.codes.OK:
        raise GitHubOAuthError(
            "token_exchange_failed",
            f"GitHub rejected the authorization code (HTTP {response.status_code}).",
        )

    payload = _safe_json(response)
    error = payload.get("error")
    if isinstance(error, str) and error:
        description = payload.get("error_description")
        message = description if isinstance(description, str) and description else error
        raise GitHubOAuthError(error, f"GitHub authorization failed: {message}")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GitHubOAuthError(
            "missing_token", "GitHub did not return an access token."
        )

    scope_value = payload.get("scope")
    granted_scopes = scope_value if isinstance(scope_value, str) else ""
    return access_token, granted_scopes


async def fetch_github_user(access_token: str) -> GitHubProfile:
    payload = await _api_get(access_token, "/user")
    raw_id = payload.get("id")
    raw_login = payload.get("login")
    if not isinstance(raw_id, int) or not isinstance(raw_login, str):
        raise GitHubAPIError("Unexpected response from GitHub /user.")
    avatar = payload.get("avatar_url")
    return GitHubProfile(
        id=raw_id,
        login=raw_login,
        avatar_url=avatar if isinstance(avatar, str) else None,
    )


async def list_user_repos(
    access_token: str,
    *,
    query: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> list[GitHubRepo]:
    """List repos the authenticated user has access to (sorted by recent activity).

    When ``query`` is set, results are filtered server-side via the GitHub search
    API (``in:name``) so private repos are included.
    """
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    cleaned_query = (query or "").strip()

    if cleaned_query:
        search_q = f"{cleaned_query} in:name user:@me fork:true"
        payload = await _api_get(
            access_token,
            "/search/repositories",
            params={"q": search_q, "per_page": per_page, "page": page, "sort": "updated"},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        raw_list: list[object] = items if isinstance(items, list) else []
    else:
        payload = await _api_get(
            access_token,
            "/user/repos",
            params={
                "sort": "updated",
                "per_page": per_page,
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        raw_list = payload if isinstance(payload, list) else []

    return [_parse_repo(item) for item in raw_list if isinstance(item, dict)]


async def list_repo_branches(
    access_token: str,
    *,
    owner: str,
    repo: str,
    per_page: int = 100,
) -> list[str]:
    payload = await _api_get(
        access_token,
        f"/repos/{owner}/{repo}/branches",
        params={"per_page": max(1, min(per_page, 100))},
    )
    raw_list = payload if isinstance(payload, list) else []
    names: list[str] = []
    for item in raw_list:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


async def revoke_user_grant(config: GitHubOAuthConfig, access_token: str) -> None:
    """Best-effort: revoke the user's grant on GitHub so future tokens fail.

    GitHub's revoke endpoint requires the App's client credentials as Basic auth
    plus the access token in the JSON body. Failures are swallowed because the
    primary disconnect (deleting the local row) has already happened.
    """
    auth = httpx.BasicAuth(config.client_id, config.client_secret)
    url = f"https://api.github.com/applications/{config.client_id}/grant"
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, auth=auth) as client:
            # httpx.AsyncClient.delete() does not accept a JSON body; fall back
            # to client.request so we can send the token GitHub expects.
            await client.request(
                "DELETE",
                url,
                json={"access_token": access_token},
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": _USER_AGENT,
                },
            )
    except httpx.HTTPError:
        return


async def _api_get(
    access_token: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> dict[str, object] | list[object]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, base_url=_API_BASE) as client:
        try:
            response = await client.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise GitHubAPIError("Could not reach GitHub.") from exc

    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise GitHubAPIError(
            "GitHub rejected the stored access token. Reconnect your account in Settings."
        )
    if response.status_code == httpx.codes.FORBIDDEN:
        raise GitHubAPIError(
            "GitHub denied the request (rate-limited or missing permissions)."
        )
    if response.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API call failed (HTTP {response.status_code})."
        )
    return _decode_json(response)


def _parse_repo(item: dict[str, object]) -> GitHubRepo:
    full_name = item.get("full_name")
    default_branch = item.get("default_branch")
    private = item.get("private")
    html_url = item.get("html_url")
    description = item.get("description")
    return GitHubRepo(
        full_name=full_name if isinstance(full_name, str) else "",
        default_branch=default_branch if isinstance(default_branch, str) else "main",
        private=bool(private) if isinstance(private, bool) else False,
        html_url=html_url if isinstance(html_url, str) else "",
        description=description if isinstance(description, str) else None,
    )


def _safe_json(response: httpx.Response) -> dict[str, object]:
    decoded = _decode_json(response)
    if isinstance(decoded, dict):
        return decoded
    raise GitHubAPIError("GitHub returned an unexpected response shape.")


def _decode_json(response: httpx.Response) -> dict[str, object] | list[object]:
    try:
        data = response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub returned an unexpected non-JSON response.") from exc
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return data
    raise GitHubAPIError("GitHub returned an unexpected response shape.")
