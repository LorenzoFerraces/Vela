"""Unit tests for the Kubernetes manifest parser."""

from __future__ import annotations

from app.core.stacks.k8s_parser import parse_k8s

MULTI_DOC_YAML = """
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
          env:
            - name: APP_ENV
              value: production
            - name: EMPTY_VAR
          envFrom:
            - configMapRef:
                name: web-config
          command: ["nginx"]
          args: ["-g", "daemon off;"]
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: cache
spec:
  template:
    spec:
      containers:
        - name: cache
          image: redis:7
          ports:
            - containerPort: 6379
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
data:
  LOG_LEVEL: debug
  FEATURE_FLAG: "true"
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  ports:
    - port: 8080
---
apiVersion: v1
kind: Secret
metadata:
  name: web-secret
"""


def test_parse_k8s_workloads() -> None:
    services, warnings = parse_k8s(MULTI_DOC_YAML)
    by_name = {s.service_name: s for s in services}

    assert set(by_name) == {"web", "cache"}
    web = by_name["web"]
    assert web.source_kind == "image"
    assert web.source_ref == "nginx:alpine"
    assert web.container_port == 8080
    assert web.env_vars["APP_ENV"] == "production"
    assert web.env_vars["EMPTY_VAR"] == ""
    assert web.command == ["nginx", "-g", "daemon off;"]
    assert web.public_route is True

    cache = by_name["cache"]
    assert cache.source_ref == "redis:7"
    assert cache.container_port == 6379
    assert cache.public_route is False


def test_parse_k8s_merges_config_map_env_from_env_from() -> None:
    services, _ = parse_k8s(MULTI_DOC_YAML)
    web = next(s for s in services if s.service_name == "web")
    assert web.env_vars["LOG_LEVEL"] == "debug"
    assert web.env_vars["FEATURE_FLAG"] == "true"
    cache = next(s for s in services if s.service_name == "cache")
    assert "LOG_LEVEL" not in cache.env_vars


def test_parse_k8s_warns_on_secret_and_orphan_service() -> None:
    _, warnings = parse_k8s(MULTI_DOC_YAML)
    assert any("Secret" in w and "web-secret" in w for w in warnings)
    orphan = "apiVersion: v1\nkind: Service\nmetadata:\n  name: lonely\n"
    _, warnings = parse_k8s(orphan)
    assert any("lonely" in w for w in warnings)


def test_parse_k8s_secret_ref_in_env_from_warns_and_skips() -> None:
    yaml_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      containers:
        - name: app
          image: myapp:1.0
          envFrom:
            - secretRef:
                name: app-secrets
"""
    services, warnings = parse_k8s(yaml_content)
    assert services[0].env_vars == {}
    assert any("app-secrets" in w for w in warnings)


def test_parse_k8s_volume_mounts_warn() -> None:
    yaml_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      containers:
        - name: app
          image: myapp:1.0
          volumeMounts:
            - name: data
              mountPath: /data
"""
    services, warnings = parse_k8s(yaml_content)
    assert len(services) == 1
    assert any("volumeMounts" in w for w in warnings)


def test_parse_k8s_sanitizes_and_deduplicates_names() -> None:
    yaml_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: My.App_One
spec:
  template:
    spec:
      containers:
        - name: a
          image: nginx:alpine
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-app-one
spec:
  template:
    spec:
      containers:
        - name: b
          image: redis:7
"""
    services, _ = parse_k8s(yaml_content)
    names = [s.service_name for s in services]
    assert names[0] == "my-app-one"
    assert names[1] == "my-app-one-2"


def test_parse_k8s_no_workloads_returns_empty() -> None:
    yaml_content = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: cfg
data:
  A: "1"
"""
    services, warnings = parse_k8s(yaml_content)
    assert services == []
    assert warnings == []


def test_parse_k8s_invalid_yaml_returns_warning() -> None:
    services, warnings = parse_k8s("not: [valid: yaml")
    assert services == []
    assert any("Invalid YAML" in w for w in warnings)


def test_parse_k8s_missing_image_defaults_to_nginx_with_warning() -> None:
    yaml_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      containers:
        - name: app
"""
    services, warnings = parse_k8s(yaml_content)
    assert services[0].source_ref == "nginx:alpine"
    assert any("no container image" in w for w in warnings)
