"""URL sanitization for user-facing display (credential stripping)."""

from urllib.parse import urlparse


def sanitize_url_for_display(url: str) -> str:
    """Remove userinfo, query, and fragment from URL for audit persistence."""
    try:
        parsed = urlparse(url)
        clean = parsed._replace(netloc=parsed.hostname or "", query="", fragment="")
        return clean.geturl()
    except ValueError:
        return url
