"""Registry image autocomplete: Docker Hub search (by pull count) plus local engine tags."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

HUB_SEARCH_URL = "https://hub.docker.com/v2/search/repositories/"

_DEFAULT_POPULAR_REFS: tuple[str, ...] = (
    "nginx:alpine",
    "nginx:latest",
    "redis:alpine",
    "postgres:16-alpine",
    "mysql:8",
    "mongo:7",
    "node:22-alpine",
    "python:3.12-slim",
    "httpd:alpine",
    "alpine:latest",
    "ubuntu:24.04",
    "busybox:latest",
    "traefik:latest",
)


@dataclass(frozen=True)
class ImageSuggestionItem:
    ref: str
    pull_count: int | None
    source: Literal["local", "registry"]


async def fetch_docker_hub_suggestions(query: str, *, page_size: int) -> list[tuple[str, int]]:
    """Return Hub repository names with pull counts, sorted by pulls (desc)."""
    stripped = query.strip()
    if not stripped:
        return []
    bounded = min(max(page_size, 1), 100)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                HUB_SEARCH_URL,
                params={"query": stripped, "page_size": str(bounded)},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Docker Hub search failed: %s", exc)
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    parsed: list[tuple[str, int]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("repo_name")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if not name:
            continue
        raw_pull = item.get("pull_count")
        pull = int(raw_pull) if isinstance(raw_pull, int) else 0
        parsed.append((name, pull))
    parsed.sort(key=lambda row: row[1], reverse=True)
    return parsed


def merge_image_suggestions(
    *,
    query: str,
    limit: int,
    local_tags: list[str],
    hub_rows: list[tuple[str, int]],
) -> list[ImageSuggestionItem]:
    """Merge local matches, a curated popular list, and Hub rows (deduped, capped)."""
    q = query.strip().lower()
    seen: set[str] = set()
    out: list[ImageSuggestionItem] = []
    local_cap = 12

    def push(
        ref: str,
        pull: int | None,
        source: Literal["local", "registry"],
    ) -> None:
        key = ref.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        out.append(
            ImageSuggestionItem(ref=ref.strip(), pull_count=pull, source=source),
        )

    if not q:
        for ref in _DEFAULT_POPULAR_REFS:
            if len(out) >= limit:
                break
            push(ref, None, "registry")
        for tag in sorted(local_tags):
            if len(out) >= limit:
                break
            push(tag, None, "local")
        return out[:limit]

    local_matches = sorted(t for t in local_tags if q in t.lower())
    for tag in local_matches[:local_cap]:
        push(tag, None, "local")
        if len(out) >= limit:
            return out[:limit]

    for ref, pull in hub_rows:
        if len(out) >= limit:
            break
        push(ref, pull, "registry")

    return out[:limit]
