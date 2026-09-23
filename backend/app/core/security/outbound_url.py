"""Validation for user-supplied outbound URLs (SSRF guard)."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

# Self-hosted deployments may point at LAN / plain-HTTP endpoints. Off by default.
ALLOW_PRIVATE_ENV = "VELA_LLM_ALLOW_PRIVATE_ENDPOINTS"


def allow_private_endpoints() -> bool:
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip() == "1"


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


def validate_outbound_url(url: str, *, label: str = "Base URL") -> str:
    """Reject non-HTTPS and non-public destinations.

    Raises ``ValueError`` for request-model validators; callers doing outbound
    transport catch it and surface a provider error instead.
    """
    if allow_private_endpoints():
        return url
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"{label} must start with https://.")
    host = parts.hostname
    if not host:
        raise ValueError(f"{label} must include a host.")
    # ponytail: sync DNS in the request validator; fine at this call rate, move to a
    # pre-connect check if a hot path needs it.
    if not _host_is_public(host):
        raise ValueError(f"{label} must resolve to a public address.")
    return url
