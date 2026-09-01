"""Unit tests for manifest sniffing (compose vs Kubernetes)."""

from __future__ import annotations

import pytest

from app.core.exceptions import ManifestParseError
from app.core.stacks.manifest_parser import parse_manifest

COMPOSE_YAML = """
services:
  web:
    image: nginx:alpine
  redis:
    image: redis:7
"""

K8S_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  template:
    spec:
      containers:
        - name: web
          image: nginx:alpine
          ports:
            - containerPort: 8080
"""


def test_parse_manifest_compose() -> None:
    services, warnings, kind = parse_manifest(COMPOSE_YAML)
    assert kind == "compose"
    assert {s.service_name for s in services} == {"web", "redis"}


def test_parse_manifest_k8s() -> None:
    services, warnings, kind = parse_manifest(K8S_YAML)
    assert kind == "k8s"
    assert services[0].service_name == "web"
    assert services[0].container_port == 8080


def test_parse_manifest_garbage_raises() -> None:
    with pytest.raises(ManifestParseError, match="Unrecognized manifest"):
        parse_manifest("hello: [world")


def test_parse_manifest_unknown_mapping_raises() -> None:
    with pytest.raises(ManifestParseError, match="Unrecognized manifest"):
        parse_manifest("foo: bar\nbaz: 1\n")


def test_parse_manifest_k8s_without_workloads_raises() -> None:
    yaml_content = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: c\ndata: {}\n"
    with pytest.raises(ManifestParseError, match="No supported Kubernetes resources"):
        parse_manifest(yaml_content)
