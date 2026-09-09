"""Sniff a manifest between Docker Compose and Kubernetes, then parse it."""

from __future__ import annotations

from typing import Literal

import yaml

from app.core.exceptions import ManifestParseError
from app.core.stacks.compose_parser import parse_compose
from app.core.stacks.k8s_parser import parse_k8s
from app.db.models import StackService


def parse_manifest(
    yaml_content: str,
) -> tuple[list[StackService], list[str], Literal["compose", "k8s"]]:
    """Parse a manifest, detecting compose vs Kubernetes.

    Returns:
        Tuple of (services, warnings, kind) where kind is "compose" or "k8s".

    Raises:
        ManifestParseError: unrecognized format or no supported resources.
    """
    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError:
        documents = []

    first = documents[0] if documents else None
    if (
        isinstance(first, dict)
        and isinstance(first.get("services"), dict)
        and first["services"]
    ):
        services, warnings = parse_compose(yaml_content)
        return services, warnings, "compose"

    if any(_is_k8s_document(document) for document in documents):
        services, warnings = parse_k8s(yaml_content)
        if not services:
            raise ManifestParseError(
                "No supported Kubernetes resources found "
                "(need Deployment or StatefulSet)."
            )
        return services, warnings, "k8s"

    raise ManifestParseError(
        "Unrecognized manifest — expected Docker Compose or Kubernetes YAML."
    )


def _is_k8s_document(document: object) -> bool:
    return (
        isinstance(document, dict)
        and isinstance(document.get("apiVersion"), str)
        and isinstance(document.get("kind"), str)
    )
