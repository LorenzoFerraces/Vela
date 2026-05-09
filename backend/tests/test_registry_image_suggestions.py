"""Unit tests for registry image autocomplete merge logic."""

from __future__ import annotations

from app.core.registry_image_suggestions import merge_image_suggestions


def test_merge_empty_query_includes_defaults_then_local() -> None:
    merged = merge_image_suggestions(
        query="",
        limit=30,
        local_tags=["zebra:1", "nginx:alpine"],
        hub_rows=[],
    )
    refs = [item.ref for item in merged]
    assert "nginx:alpine" in refs
    assert "zebra:1" in refs
    assert merged[0].source == "registry"


def test_merge_search_prefers_local_matches_then_hub_by_pulls() -> None:
    merged = merge_image_suggestions(
        query="nginx",
        limit=10,
        local_tags=["my/nginx:dev", "nginx:alpine"],
        hub_rows=[
            ("nginx", 1_000_000),
            ("other/nginx", 100),
        ],
    )
    refs = [item.ref for item in merged]
    assert refs.index("my/nginx:dev") < refs.index("nginx")
    assert refs.index("nginx:alpine") < refs.index("nginx")
    hub_nginx = next(item for item in merged if item.ref == "nginx")
    assert hub_nginx.pull_count == 1_000_000
    assert hub_nginx.source == "registry"


def test_merge_respects_limit() -> None:
    merged = merge_image_suggestions(
        query="x",
        limit=3,
        local_tags=["a/x:1", "b/x:2", "c/x:3", "d/x:4"],
        hub_rows=[("x/foo", 9), ("x/bar", 8)],
    )
    assert len(merged) == 3
