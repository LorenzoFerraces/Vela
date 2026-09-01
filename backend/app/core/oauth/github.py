"""GitHub OAuth App client (authorize URL, token exchange, REST helpers).

Only this module talks to GitHub directly so token-handling code lives in one
place. All HTTP goes through ``httpx.AsyncClient``; the access token is never
logged or returned to callers verbatim except by the higher-level service that
encrypts it for storage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.core.exceptions import GitHubAPIError, GitHubOAuthError, IntegrationConfigurationError

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - public endpoint, not a secret
_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)
_DEFAULT_SCOPES = "repo,read:user"
_USER_AGENT = "vela-backend"
_MAX_ACCESSIBLE_REPO_PAGES = 10


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


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str


@dataclass(frozen=True)
class RepoLookupOutcome:
    repo: GitHubRepo | None = None
    org_sso_authorize_url: str | None = None


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


def parse_github_repo_url(raw: str) -> GitHubRepoRef | None:
    """
    Extract ``owner`` and ``repo`` from common GitHub clone or browse URLs.

    Supports HTTPS, SSH, and ``git@`` forms, including paths such as
    ``/tree/branch`` or a trailing ``.git``.
    """
    stripped = raw.strip()
    if not stripped:
        return None

    if stripped.startswith("git@"):
        host, _, path = stripped.partition(":")
        if not path or "github.com" not in host.removeprefix("git@"):
            return None
        return _github_repo_ref_from_path(path)

    try:
        parsed = urlparse(stripped)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host != "github.com" and not host.endswith(".github.com"):
        return None
    if parsed.scheme not in {"http", "https", "ssh"}:
        return None
    return _github_repo_ref_from_path(parsed.path)


async def fetch_user_repo_if_accessible(
    access_token: str,
    *,
    owner: str,
    repo: str,
) -> RepoLookupOutcome:
    """
    Return repository metadata when the authenticated user can access it.

    When GitHub requires organization SSO authorization, the outcome includes
  ``org_sso_authorize_url`` so the UI can link the user to approve access.
    """
    from app.e2e_support import e2e_github_repo_if_accessible

    fixture_repo = e2e_github_repo_if_accessible(
        access_token,
        owner=owner,
        repo=repo,
    )
    if fixture_repo is not None:
        return RepoLookupOutcome(repo=fixture_repo)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, base_url=_API_BASE) as client:
        try:
            response = await client.get(
                f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise GitHubAPIError("Could not reach GitHub.") from exc

    if response.status_code == httpx.codes.FORBIDDEN:
        return RepoLookupOutcome(
            org_sso_authorize_url=_parse_github_sso_authorize_url(response),
        )
    if response.status_code == httpx.codes.NOT_FOUND:
        return RepoLookupOutcome()
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise GitHubAPIError(
            "GitHub rejected the stored access token. Reconnect your account in Settings."
        )
    if response.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API call failed (HTTP {response.status_code})."
        )

    payload = _decode_json(response)
    if not isinstance(payload, dict):
        raise GitHubAPIError("GitHub returned an unexpected response shape.")
    return RepoLookupOutcome(repo=_parse_repo(payload))


async def find_accessible_repo_by_name(
    access_token: str,
    *,
    repo_name: str,
    preferred_owners: list[str],
) -> RepoLookupOutcome:
    """Resolve a repository the user can access by exact repo name."""
    normalized_repo = repo_name.strip().lower()
    if not normalized_repo:
        return RepoLookupOutcome()

    owners_to_try: list[str] = []
    seen_owners: set[str] = set()
    org_sso_authorize_url: str | None = None

    for owner in preferred_owners:
        cleaned_owner = owner.strip()
        if not cleaned_owner:
            continue
        lowered = cleaned_owner.lower()
        if lowered in seen_owners:
            continue
        seen_owners.add(lowered)
        owners_to_try.append(cleaned_owner)

    try:
        profile = await fetch_github_user(access_token)
        if profile.login:
            lowered = profile.login.lower()
            if lowered not in seen_owners:
                seen_owners.add(lowered)
                owners_to_try.append(profile.login)
    except GitHubAPIError:
        pass

    for owner in owners_to_try:
        outcome = await fetch_user_repo_if_accessible(
            access_token,
            owner=owner,
            repo=repo_name,
        )
        if outcome.org_sso_authorize_url and org_sso_authorize_url is None:
            org_sso_authorize_url = outcome.org_sso_authorize_url
        if outcome.repo is not None:
            return outcome

    for owner in owners_to_try:
        repo = await _search_repo_for_owner(
            access_token,
            owner=owner,
            repo_name=repo_name,
        )
        if repo is not None:
            return RepoLookupOutcome(repo=repo)

    accessible_repos = await _list_all_accessible_user_repos(access_token)
    matches = [
        row
        for row in accessible_repos
        if row.full_name
        and row.full_name.rsplit("/", maxsplit=1)[-1].lower() == normalized_repo
    ]
    if matches:
        for owner in owners_to_try:
            lowered_owner = owner.lower()
            for row in matches:
                owner_name, _, name = row.full_name.partition("/")
                if (
                    owner_name.lower() == lowered_owner
                    and name.lower() == normalized_repo
                ):
                    return RepoLookupOutcome(repo=row)
        return RepoLookupOutcome(repo=matches[0])

    return RepoLookupOutcome(org_sso_authorize_url=org_sso_authorize_url)


async def _search_repo_for_owner(
    access_token: str,
    *,
    owner: str,
    repo_name: str,
) -> GitHubRepo | None:
    search_term = repo_name
    if " " not in search_term and "/" not in search_term:
        search_term = f'"{search_term}"'
    normalized_repo = repo_name.strip().lower()
    for qualifier in ("user", "org"):
        search_q = f"{qualifier}:{owner} {search_term} in:name"
        try:
            payload = await _api_get(
                access_token,
                "/search/repositories",
                params={"q": search_q, "per_page": 10, "page": 1, "sort": "updated"},
            )
        except GitHubAPIError:
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        raw_list = items if isinstance(items, list) else []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            repo = _parse_repo(item)
            if (
                repo.full_name
                and repo.full_name.rsplit("/", maxsplit=1)[-1].lower() == normalized_repo
            ):
                return repo
    return None


async def _list_all_accessible_user_repos(access_token: str) -> list[GitHubRepo]:
    all_repos: list[GitHubRepo] = []
    for page in range(1, _MAX_ACCESSIBLE_REPO_PAGES + 1):
        try:
            batch = await list_user_repos(
                access_token,
                query=None,
                page=page,
                per_page=100,
            )
        except GitHubAPIError:
            break
        if not batch:
            break
        all_repos.extend(batch)
        if len(batch) < 100:
            break
    return all_repos


async def list_user_repos(
    access_token: str,
    *,
    query: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> list[GitHubRepo]:
    """
    List repositories the authenticated user can access, ordered by recent activity.
    
    When `query` is provided, the function uses the GitHub search API (searching `in:name` and including forks and private repos accessible to the user). When `query` is empty or blank, the function lists repositories from the authenticated user's repositories endpoint and includes owner, collaborator, and organization member affiliations. Pagination parameters are clamped: `page` is at least 1 and `per_page` is between 1 and 100. For end-to-end testing, this function first consults `app.e2e_support.e2e_github_repos_if_enabled(...)` and returns any non-`None` fixture list immediately.
    
    Parameters:
        access_token (str): A valid GitHub access token for the authenticated user.
        query (str | None): Optional search string; blank or `None` triggers the standard user repos listing.
        page (int): Page number for pagination (minimum 1).
        per_page (int): Number of results per page (clamped to the range 1–100).
    
    Returns:
        list[GitHubRepo]: A list of parsed repository records representing the matching repositories.
    """
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    cleaned_query = (query or "").strip()

    from app.e2e_support import e2e_github_repos_if_enabled

    fixture_repos = e2e_github_repos_if_enabled(
        access_token,
        query=cleaned_query or None,
        page=page,
        per_page=per_page,
    )
    if fixture_repos is not None:
        return fixture_repos

    if cleaned_query:
        search_term = cleaned_query
        if " " not in search_term and "/" not in search_term:
            search_term = f'"{search_term}"'
        search_q = f"{search_term} in:name user:@me fork:true"
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
                "type": "all",
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


def _parse_github_sso_authorize_url(response: httpx.Response) -> str | None:
    header = response.headers.get("X-GitHub-SSO", "")
    lowered = header.lower()
    marker = "url="
    if marker not in lowered:
        return None
    start = lowered.index(marker) + len(marker)
    url = header[start:].strip().strip('"')
    return url or None


def _github_repo_ref_from_path(path: str) -> GitHubRepoRef | None:
    cleaned = path.strip().strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    parts = [segment for segment in cleaned.split("/") if segment]
    if len(parts) < 2:
        return None
    return GitHubRepoRef(owner=parts[0], repo=parts[1])


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
