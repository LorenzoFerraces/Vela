"""Validation for user-supplied outbound URLs (SSRF guard)."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

# Self-hosted deployments may point at LAN / plain-HTTP endpoints. Off by default.
ALLOW_PRIVATE_ENV = "VELA_LLM_ALLOW_PRIVATE_ENDPOINTS"


def allow_private_endpoints(*, env: str = ALLOW_PRIVATE_ENV) -> bool:
    return os.environ.get(env, "").strip() == "1"


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Unresolvable here: the outbound request will fail on its own.
        return True
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not parsed.is_global:
            return False
    return True


def validate_outbound_url(
    url: str, *, label: str = "Base URL", allow_private_env: str = ALLOW_PRIVATE_ENV
) -> str:
    """Reject non-HTTPS and non-public destinations.

    Raises ``ValueError`` for request-model validators; callers doing outbound
    transport catch it and surface a provider error instead.
    """
    if allow_private_endpoints(env=allow_private_env):
        return url
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"{label} must start with https://.")
    host = parts.hostname
    if not host:
        raise ValueError(f"{label} must include a host.")
    # ponytail: sync DNS in the request validator; fine at this call rate.
    if not _host_is_public(host):
        raise ValueError(f"{label} must resolve to a public address.")
    return url


def validate_git_remote(url: str) -> str:
    """Apply the outbound SSRF guard to Git clone URLs (SSH remotes use host checks)."""
    from urllib.parse import urlsplit

    stripped = url.strip()
    lowered = stripped.lower()
    if lowered.startswith("git@"):
        host = stripped.split("@", 1)[1].split(":", 1)[0]
    elif lowered.startswith(("ssh://", "git://")):
        host = urlsplit(stripped).hostname or ""
    elif lowered.startswith(("http://", "https://")):
        if not allow_private_endpoints(env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS"):
            return validate_outbound_url(
                stripped, label="Git URL",
                allow_private_env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS",
            )
        return stripped
    else:
        raise ValueError("Git URL must be an http(s), ssh, git:// or git@ remote.")
    if not host:
        raise ValueError("Git URL must include a host.")
    if not allow_private_endpoints(env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS") and not _host_is_public(host):
        raise ValueError("Git URL must resolve to a public address.")
    return stripped
