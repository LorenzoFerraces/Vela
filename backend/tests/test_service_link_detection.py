"""Unit tests for stack service-link detection heuristics (mirrors frontend)."""

from __future__ import annotations

import re


def find_service_name_matches(value: str, sibling_names: list[str]) -> list[tuple[str, int, int]]:
    sorted_names = sorted(
        [name for name in sibling_names if name.strip()],
        key=len,
        reverse=True,
    )
    matches: list[tuple[str, int, int]] = []
    for service_name in sorted_names:
        pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(service_name)}(?![A-Za-z0-9_-])")
        for match in pattern.finditer(value):
            # Skip URL schemes (e.g. mongodb://...) — only hostnames are links.
            if value[match.end() : match.end() + 3] == "://":
                continue
            matches.append((service_name, match.start(), match.end()))
    matches.sort(key=lambda item: (item[1], -item[2]))
    non_overlapping: list[tuple[str, int, int]] = []
    cursor = 0
    for service_name, start, end in matches:
        if start < cursor:
            continue
        non_overlapping.append((service_name, start, end))
        cursor = end
    return non_overlapping


def test_finds_hostname_style_service_names() -> None:
    siblings = ["postgres", "mongodb", "neo4j", "app"]
    assert [
        name
        for name, _, _ in find_service_name_matches(
            "jdbc:postgresql://postgres:5432/${POSTGRES_DB}", siblings
        )
    ] == ["postgres"]
    assert [
        name
        for name, _, _ in find_service_name_matches(
            "mongodb://mongodb:27017/${MONGODB_DATABASE}", siblings
        )
    ] == ["mongodb"]
    assert [
        name for name, _, _ in find_service_name_matches("bolt://neo4j:7687", siblings)
    ] == ["neo4j"]


def test_variable_names_are_not_service_links() -> None:
    siblings = ["postgres", "mongodb", "neo4j"]
    matches = find_service_name_matches("${POSTGRES_USER:-admin}", siblings)
    assert matches == []
