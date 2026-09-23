# Stacks Flow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stacks table with a card picker and stack creation with a multi-step New Stack modal (file / repo / manual), adding a deterministic Kubernetes parser and provider-agnostic LLM (Vertex AI + Gemini) stack generation.

**Architecture:** Backend gains `k8s_parser.py`, a `parse-manifest` endpoint (compose/k8s sniffing), an `analyze-repo` endpoint (clone → detect compose → k8s → LLM fallback) and a shared `app/core/llm/` module extracted from the existing Gemini code with a Vertex backend. Frontend gets a card grid on `StacksPage` and a `NewStackModal` reusing the existing `stacks-modal` shell; the old compose import page is deleted.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, PyYAML, httpx · React 19 + TypeScript, React Router 7, Phosphor icons, Vite · Pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-28-stacks-flow-redesign-design.md`

## Global Constraints

- **Comments:** Do not add inline comments unless asked (repo rule). Docstrings only where the surrounding module style has them (e.g. `compose_parser.py`).
- **Colors:** All frontend colors from existing `:root` tokens in `frontend/src/index.css` (`--bg-elevated`, `--border`, `--text`, `--text-muted`, `--text-heading`, `--accent`, `--accent-soft`, `--ok`, `--error`, ...). No raw hex/rgba.
- **CSS:** New page-specific styles go in a separate CSS file imported by the page — do not grow `index.css`. Animations must be disabled under `@media (prefers-reduced-motion: reduce)`.
- **A11y:** `role="dialog"` + `aria-modal` + `aria-labelledby` on modals; Escape closes; focus restored on close; `aria-hidden="true"` on decorative icons; visible focus rings everywhere; errors near the field with `role="alert"`.
- **Errors:** Client-facing messages only, never stack traces or internal details (existing mapping patterns in `backend/app/api/errors.py`).
- **Python style:** explicit, typed, match surrounding modules (see `app/core/stacks/compose_parser.py`, `app/core/git/git_source_analysis.py`).
- **Verification:** `cd backend && python -m pytest tests -q` must pass after backend tasks; `cd frontend && npm run lint && npm run build` after frontend tasks; Playwright `npm run test:e2e` at the end. Do not claim done without all green.
- **E2E rule:** No `page.route` mocking for app flows; backend fixtures via `app/e2e_support.py`.
- **Commits:** one commit per task, message style `F/stacks: <description>` (matches recent repo history).

---

### Task 1: Kubernetes manifest parser

**Files:**
- Create: `backend/app/core/stacks/k8s_parser.py`
- Test: `backend/tests/test_k8s_parser.py`

**Interfaces:**
- Consumes: `yaml.safe_load_all`; `StackService` ORM model (`backend/app/db/models.py`); `sanitize_container_name` from `app.core.git.git_source_analysis`.
- Produces: `parse_k8s(yaml_content: str) -> tuple[list[StackService], list[str]]` — same return shape as `parse_compose` in `app/core/stacks/compose_parser.py`. Also `SUPPORTED_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}` and `_file_has_workload_kind(path: Path) -> bool` (used by Task 4).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_k8s_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k8s_parser.py -q` (from `backend/`)
Expected: collection error — `ModuleNotFoundError: app.core.stacks.k8s_parser`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/stacks/k8s_parser.py`:

```python
"""Parse Kubernetes manifests into StackService records."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.core.git.git_source_analysis import sanitize_container_name
from app.db.models import StackService

SUPPORTED_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


def parse_k8s(yaml_content: str) -> tuple[list[StackService], list[str]]:
    """Parse Kubernetes manifest YAML (multi-document) into StackService records.

    Returns:
        Tuple of (services, warnings). Warnings describe unsupported features
        that were dropped. Returns empty services when no workload resources exist.
    """
    try:
        documents = [
            document
            for document in yaml.safe_load_all(yaml_content)
            if isinstance(document, dict)
        ]
    except yaml.YAMLError:
        return [], ["Invalid YAML: could not parse the manifest."]

    warnings: list[str] = []
    config_maps: dict[str, dict[str, str]] = {}
    ingress_backend_names: set[str] = set()
    service_kind_names: list[str] = []
    workloads: list[tuple[StackService, list[str]]] = []

    for document in documents:
        kind = document.get("kind")
        if kind in SUPPORTED_WORKLOAD_KINDS:
            service, config_map_refs = _parse_workload(document, warnings)
            workloads.append((service, config_map_refs))
        elif kind == "ConfigMap":
            name = _doc_name(document)
            data = document.get("data")
            if name and isinstance(data, dict):
                config_maps[name] = {str(k): str(v) for k, v in data.items()}
        elif kind == "Ingress":
            ingress_backend_names |= _ingress_backend_service_names(document)
        elif kind == "Service":
            name = _doc_name(document)
            if name:
                service_kind_names.append(name)
        elif kind == "Secret":
            name = _doc_name(document)
            warnings.append(
                f"Secret '{name or 'unnamed'}' skipped — secrets cannot be "
                "imported. Add env vars manually."
            )
        elif kind == "PersistentVolumeClaim":
            warnings.append(
                f"PersistentVolumeClaim '{_doc_name(document) or 'unnamed'}' "
                "skipped — add volumes manually."
            )

    for service, config_map_refs in workloads:
        for config_map_name in config_map_refs:
            if config_map_name in config_maps:
                service.env_vars = {**config_maps[config_map_name], **service.env_vars}
            else:
                warnings.append(
                    f"Service '{service.service_name}': ConfigMap "
                    f"'{config_map_name}' not found in the manifest."
                )
        if service.service_name in ingress_backend_names:
            service.public_route = True

    workload_names = {service.service_name for service, _ in workloads}
    for orphan_name in service_kind_names:
        if orphan_name not in workload_names:
            warnings.append(
                f"Kubernetes Service '{orphan_name}' has no matching "
                "Deployment/StatefulSet and was ignored."
            )

    services = _deduplicate_names([service for service, _ in workloads])
    return services, warnings


def _file_has_workload_kind(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for document in yaml.safe_load_all(text):
            if (
                isinstance(document, dict)
                and document.get("kind") in SUPPORTED_WORKLOAD_KINDS
                and isinstance(document.get("apiVersion"), str)
            ):
                return True
    except (OSError, yaml.YAMLError):
        return False
    return False


def _doc_name(document: dict) -> str:
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("name") or "")
    return ""


def _parse_workload(
    document: dict,
    warnings: list[str],
) -> tuple[StackService, list[str]]:
    raw_name = _doc_name(document)
    name = sanitize_container_name(raw_name) or "service"

    spec = document.get("spec") or {}
    template_spec = (spec.get("template") or {}).get("spec") or {}
    containers = template_spec.get("containers") or []
    container = containers[0] if containers else {}

    image = str(container.get("image") or "").strip()
    if not image:
        warnings.append(
            f"Workload '{raw_name}': no container image, defaulting to 'nginx:alpine'."
        )
        image = "nginx:alpine"

    container_port = 80
    ports = container.get("ports")
    if isinstance(ports, list) and ports and isinstance(ports[0], dict):
        try:
            container_port = int(ports[0].get("containerPort"))
        except (TypeError, ValueError):
            pass

    env_vars: dict[str, str] = {}
    for entry in container.get("env") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("name") or "").strip()
        if not key:
            continue
        value = entry.get("value")
        env_vars[key] = "" if value is None else str(value)

    config_map_refs: list[str] = []
    for source in container.get("envFrom") or []:
        if not isinstance(source, dict):
            continue
        config_map_ref = source.get("configMapRef")
        if isinstance(config_map_ref, dict):
            ref_name = str(config_map_ref.get("name") or "")
            if ref_name:
                config_map_refs.append(ref_name)
            continue
        secret_ref = source.get("secretRef")
        if isinstance(secret_ref, dict):
            warnings.append(
                f"Service '{name}': secretRef "
                f"'{secret_ref.get('name') or 'unnamed'}' skipped — "
                "add env vars manually."
            )

    tokens: list[str] | None = None
    command = container.get("command")
    args = container.get("args")
    combined = [str(token) for token in (command or []) + (args or [])]
    if combined:
        tokens = combined

    if container.get("volumeMounts"):
        warnings.append(
            f"Service '{name}': volumeMounts skipped — add volumes manually."
        )

    service = StackService(
        service_name=name,
        source_kind="image",
        source_ref=image,
        git_branch=None,
        container_port=container_port,
        env_vars=env_vars,
        command=tokens,
        public_route=False,
        depends_on=None,
    )
    return service, config_map_refs


def _ingress_backend_service_names(document: dict) -> set[str]:
    names: set[str] = set()
    rules = (document.get("spec") or {}).get("rules") or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        paths = ((rule.get("http") or {}).get("paths")) or []
        for path_entry in paths:
            if not isinstance(path_entry, dict):
                continue
            backend = path_entry.get("backend") or {}
            backend_service = backend.get("service")
            if isinstance(backend_service, dict):
                name = str(backend_service.get("name") or "")
                if name:
                    names.add(sanitize_container_name(name) or name)
    return names


def _deduplicate_names(services: list[StackService]) -> list[StackService]:
    seen: set[str] = set()
    result: list[StackService] = []
    for service in services:
        name = service.service_name
        if name in seen:
            suffix = 2
            while f"{name}-{suffix}" in seen:
                suffix += 1
            name = f"{name}-{suffix}"
            service.service_name = name
        seen.add(name)
        result.append(service)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k8s_parser.py -q` (from `backend/`)
Expected: all 9 tests PASS.

- [ ] **Step 5: Run full backend suite**

Run: `python -m pytest tests -q` (from `backend/`)
Expected: PASS (nothing regressed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/stacks/k8s_parser.py backend/tests/test_k8s_parser.py
git commit -m "F/stacks: Kubernetes manifest parser"
```

---

### Task 2: `parse-manifest` endpoint (replaces `parse-compose` and `import-compose`)

**Files:**
- Create: `backend/app/core/stacks/manifest_parser.py`
- Modify: `backend/app/api/schemas.py` (replace `ComposeParseRequest/ComposeParseResponse` at lines 801-807; delete `ComposeImportRequest/ComposeImportResponse` at lines 790-798)
- Modify: `backend/app/api/routes/stacks.py` (replace `parse_compose_yaml` route, delete `import_compose` route, update imports)
- Modify: `backend/app/api/errors.py` (add `ManifestParseError` handler)
- Modify: `backend/app/core/exceptions.py` (add `ManifestParseError(StackError)`)
- Modify: `backend/tests/test_api_integration.py` (update parse-compose tests, replace import-compose test)
- Modify: `backend/tests/test_stack_permissions.py` (drop the `import-compose` assertion, ~line 48-56)
- Test: `backend/tests/test_manifest_parser.py`

**Interfaces:**
- Consumes: `parse_compose` (existing), `parse_k8s` + `SUPPORTED_WORKLOAD_KINDS` (Task 1).
- Produces: `parse_manifest(yaml_content: str) -> tuple[list[StackService], list[str], str]` (kind is `"compose"` or `"k8s"`, raises `ManifestParseError`); schemas `ManifestParseRequest { yaml_content: str }` and `ManifestParseResponse { services: list[StackServiceCreate], warnings: list[str], manifest_kind: Literal["compose", "k8s"] }`; route `POST /api/stacks/parse-manifest`.

- [ ] **Step 1: Write the failing unit test**

Create `backend/tests/test_manifest_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest_parser.py -q` (from `backend/`)
Expected: FAIL — `ManifestParseError` / `manifest_parser` not found.

- [ ] **Step 3: Add the exception and handler**

In `backend/app/core/exceptions.py`, after `StackCompositionCycleError` (line ~395):

```python
class ManifestParseError(StackError):
    """Uploaded/checked-in manifest could not be recognized or parsed."""
```

In `backend/app/api/errors.py`, import `ManifestParseError` (add to the existing `from app.core.exceptions import ...` block) and register a handler next to the other stack handlers:

```python
    @app.exception_handler(ManifestParseError)
    async def manifest_parse_handler(
        _request: Request, exc: ManifestParseError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)}
        )
```

- [ ] **Step 4: Implement the sniffing module**

Create `backend/app/core/stacks/manifest_parser.py`:

```python
"""Sniff a manifest between Docker Compose and Kubernetes, then parse it."""

from __future__ import annotations

import yaml

from app.core.exceptions import ManifestParseError
from app.core.stacks.compose_parser import parse_compose
from app.core.stacks.k8s_parser import SUPPORTED_WORKLOAD_KINDS, parse_k8s
from app.db.models import StackService


def parse_manifest(
    yaml_content: str,
) -> tuple[list[StackService], list[str], str]:
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
        and document.get("kind") in SUPPORTED_WORKLOAD_KINDS
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_manifest_parser.py -q` (from `backend/`)
Expected: all 5 PASS.

- [ ] **Step 6: Add schemas, replace the route, delete old endpoints**

In `backend/app/api/schemas.py`, replace lines 790-807 (`ComposeImportRequest`, `ComposeImportResponse`, `ComposeParseRequest`, `ComposeParseResponse`) with:

```python
class ManifestParseRequest(BaseModel):
    yaml_content: str


class ManifestParseResponse(BaseModel):
    services: list[StackServiceCreate]
    warnings: list[str] = []
    manifest_kind: Literal["compose", "k8s"]
```

In `backend/app/api/routes/stacks.py`:
- Update schema imports: replace `ComposeImportRequest, ComposeImportResponse, ComposeParseRequest, ComposeParseResponse` with `ManifestParseRequest, ManifestParseResponse`; keep `StackServiceCreate` (still used by `_orm_service_to_create`).
- Replace `from app.core.stacks.compose_parser import parse_compose` with `from app.core.stacks.manifest_parser import parse_manifest`.
- Delete the whole `import_compose` route (lines 132-156).
- Replace the `parse_compose_yaml` route with (place it before the `/{stack_id}` routes):

```python
@router.post("/parse-manifest", response_model=ManifestParseResponse)
async def parse_manifest_route(
    body: ManifestParseRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManifestParseResponse:
    _ = current_user
    services, warnings, manifest_kind = parse_manifest(body.yaml_content)
    if not services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Manifest contains no valid services.",
        )
    return ManifestParseResponse(
        services=[_orm_service_to_create(service) for service in services],
        warnings=warnings,
        manifest_kind=manifest_kind,  # type: ignore[arg-type]
    )
```

- [ ] **Step 7: Update existing tests**

In `backend/tests/test_api_integration.py`:
- `test_stack_parse_compose` (~line 1330): change the endpoint to `/api/stacks/parse-manifest` and add `assert data["manifest_kind"] == "compose"` after the status check. Rename the function to `test_stack_parse_manifest_compose`.
- `test_stack_parse_compose_git_url` (~line 1364): change endpoint to `/api/stacks/parse-manifest`. Rename to `test_stack_parse_manifest_git_url`.
- `test_stack_parse_compose_empty` (~line 1379): replace with:

```python
def test_stack_parse_manifest_unrecognized(api_client: TestClient) -> None:
    resp = api_client.post("/api/stacks/parse-manifest", json={"yaml_content": "foo: bar"})
    assert resp.status_code == 400
    assert "unrecognized manifest" in resp.json()["detail"].lower()
```

- Replace `test_stack_import_compose` (the block ending ~line 1327 that posts to `/api/stacks/import-compose`) with:

```python
def test_stack_parse_manifest_k8s(api_client: TestClient) -> None:
    k8s_yaml = """
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
    resp = api_client.post("/api/stacks/parse-manifest", json={"yaml_content": k8s_yaml})
    assert resp.status_code == 200
    data = resp.json()
    assert data["manifest_kind"] == "k8s"
    assert data["services"][0]["service_name"] == "web"
    assert data["services"][0]["container_port"] == 8080
```

In `backend/tests/test_stack_permissions.py`, delete the `import_denied` block (~lines 48-56, the POST to `/api/stacks/import-compose` and its assert). The remaining `deploy_denied` and `create_denied` assertions stay. Rename the test to `test_viewer_cannot_create_or_deploy_stack`.

- [ ] **Step 8: Run full backend suite**

Run: `python -m pytest tests -q` (from `backend/`)
Expected: PASS. First grep for leftovers: `rg "parse-compose|import-compose" backend/` — update any remaining references the same way.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/stacks/manifest_parser.py backend/app/api/schemas.py backend/app/api/routes/stacks.py backend/app/api/errors.py backend/app/core/exceptions.py backend/tests/test_manifest_parser.py backend/tests/test_api_integration.py backend/tests/test_stack_permissions.py
git commit -m "F/stacks: parse-manifest endpoint replacing parse/import-compose"
```

---

### Task 3: Provider-agnostic LLM transport

**Files:**
- Create: `backend/app/core/llm/__init__.py`
- Create: `backend/app/core/llm/provider.py`
- Create: `backend/app/core/llm/client.py`
- Modify: `backend/app/core/exceptions.py`
- Modify: `backend/app/api/errors.py`
- Modify: `backend/app/core/git/git_source_analysis.py`
- Test: `backend/tests/test_llm_provider.py`

**Interfaces:**
- `resolve_llm_config() -> LlmConfig | None`
- `async generate_json(*, prompt: str, schema: dict) -> dict`
- Vertex takes priority when `VELA_VERTEX_API_KEY` and `VELA_VERTEX_PROJECT_ID` are present; Gemini remains the fallback.

- [ ] **Step 1: Write provider tests**

Create `backend/tests/test_llm_provider.py` with a fixture that clears `VELA_VERTEX_API_KEY`, `VELA_VERTEX_PROJECT_ID`, `VELA_VERTEX_LOCATION`, `VELA_VERTEX_MODEL`, `VELA_GEMINI_API_KEY`, and `VELA_GEMINI_MODEL`. Assert:

```python
def test_vertex_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "vertex-key")
    monkeypatch.setenv("VELA_VERTEX_PROJECT_ID", "project")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "vertex"
    assert config.headers == {"x-goog-api-key": "vertex-key"}
    assert config.params == {}
    assert "locations/us-central1" in config.url
    assert "gemini-2.5-flash:generateContent" in config.url


def test_vertex_overrides_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "key")
    monkeypatch.setenv("VELA_VERTEX_PROJECT_ID", "project")
    monkeypatch.setenv("VELA_VERTEX_LOCATION", "europe-west1")
    monkeypatch.setenv("VELA_VERTEX_MODEL", "gemini-2.5-pro")
    config = resolve_llm_config()
    assert config is not None
    assert "europe-west1-aiplatform.googleapis.com" in config.url
    assert config.model == "gemini-2.5-pro"


def test_gemini_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "gemini-key")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "gemini"
    assert config.params == {"key": "gemini-key"}
    assert config.headers == {}
    assert "gemini-2.0-flash:generateContent" in config.url


def test_incomplete_vertex_config_falls_back_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "vertex-key")
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "gemini-key")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "gemini"


def test_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_llm_config() is None
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m pytest tests/test_llm_provider.py -q` from `backend/`.
Expected: collection failure because `app.core.llm.provider` does not exist.

- [ ] **Step 3: Implement provider resolution**

Create `provider.py` with a typed dataclass containing `provider`, `url`, `headers`, `params`, and `model`. Build the Vertex URL as:

```text
https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent
```

Use defaults `us-central1`, `gemini-2.5-flash`, and `gemini-2.0-flash` for Vertex and direct Gemini respectively. Never include the Vertex key in query parameters; use `x-goog-api-key`. Return `None` when neither provider is complete.

- [ ] **Step 4: Implement shared JSON generation**

Create `client.py`. Resolve the config, raise `LlmNotConfiguredError("AI analysis is not configured on this server.")` when absent, and send the existing Gemini-compatible payload with `responseMimeType: application/json` and the passed `responseSchema`. Use `httpx.AsyncClient(timeout=60.0)`, `raise_for_status()`, and parse `candidates[0].content.parts[0].text` as a JSON object. Log provider and bounded response detail server-side only. Convert HTTP, missing-field, type, and JSON errors into `LlmCallError("Could not complete AI analysis. Try again later.")` or `LlmCallError("AI analysis returned an invalid response. Try again later.")`.

Export `generate_json`, `LlmConfig`, and `resolve_llm_config` from `__init__.py`.

Add `LlmNotConfiguredError` and `LlmCallError` to `app/core/exceptions.py`. Register both in `app/api/errors.py` with a 503 response containing only `detail`.

- [ ] **Step 5: Refactor existing Gemini analysis without changing behavior**

In `git_source_analysis.py`, preserve `GIT_SOURCE_ANALYSIS_PROMPT_V1`, `_analysis_json_schema`, `_payload_to_analysis`, environment fallback, and sanitization. Replace the inline HTTP request in `_call_gemini` with `generate_json(prompt=..., schema=...)`. Translate shared LLM exceptions to the existing `GitSourceAnalysisError` messages so `/api/builder/analyze-source` keeps its public behavior. Replace the key-presence branch in `analyze_git_source` with `resolve_llm_config() is None`. Remove now-unused `httpx`, `os`, Gemini URL, model, and key helper code.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_llm_provider.py tests/test_git_source_analysis_context.py tests/test_deploy_epic.py::test_analyze_git_source_e2e_fixture -q` from `backend/`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/llm backend/app/core/exceptions.py backend/app/api/errors.py backend/app/core/git/git_source_analysis.py backend/tests/test_llm_provider.py
git commit -m "F/stacks: provider-agnostic LLM transport"
```

---

### Task 4: Repository analysis and LLM stack generation

**Files:**
- Create: `backend/app/core/stacks/repo_analysis.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes/stacks.py`
- Modify: `backend/app/e2e_support.py`
- Test: `backend/tests/test_stack_repo_analysis.py`

**Interfaces:**
- `detect_manifest_file(root: Path) -> tuple[Path, Literal["compose", "k8s"]] | None`
- `async analyze_repo_stack(image_builder: DefaultImageBuilder, *, git_url: str, git_branch: str, access_token: str | None) -> RepoStackAnalysis`
- `RepoStackAnalysis` fields: `services`, `warnings`, `manifest_kind`, `manifest_path`, `summary_hint`.
- `POST /api/stacks/analyze-repo` returns `AnalyzeRepoResponse` with `services`, `warnings`, `manifest_kind`, `manifest_path`, and `summary_hint`.

- [ ] **Step 1: Write detection tests**

Create `backend/tests/test_stack_repo_analysis.py` using `tmp_path` fixtures. Cover these exact cases:

```python
def test_root_docker_compose_wins(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    path, kind = detect_manifest_file(tmp_path) or (None, None)
    assert path == tmp_path / "docker-compose.yml"
    assert kind == "compose"


def test_top_level_compose_is_found(tmp_path: Path) -> None:
    directory = tmp_path / "deploy"
    directory.mkdir()
    (directory / "compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    result = detect_manifest_file(tmp_path)
    assert result == (directory / "compose.yml", "compose")


def test_preferred_k8s_directory_wins(tmp_path: Path) -> None:
    (tmp_path / "random.yaml").write_text(K8S_FILE, encoding="utf-8")
    directory = tmp_path / "k8s"
    directory.mkdir()
    (directory / "app.yaml").write_text(K8S_FILE, encoding="utf-8")
    assert detect_manifest_file(tmp_path) == (directory / "app.yaml", "k8s")


def test_non_manifest_yaml_and_ignored_directories_are_skipped(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "plain.yaml").write_text("name: value\n", encoding="utf-8")
    assert detect_manifest_file(tmp_path) is None


def test_compose_wins_over_k8s(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
    (tmp_path / "k8s.yaml").write_text(K8S_FILE, encoding="utf-8")
    result = detect_manifest_file(tmp_path)
    assert result is not None
    assert result[1] == "compose"
```

- [ ] **Step 2: Run detection tests and confirm failure**

Run: `python -m pytest tests/test_stack_repo_analysis.py -q` from `backend/`.
Expected: collection failure because `repo_analysis.py` does not exist.

- [ ] **Step 3: Implement deterministic detection**

Create `repo_analysis.py`. Search in this order:

1. Root files in this exact priority: `docker-compose.yml`, `docker-compose.yaml`, `compose.yml`, `compose.yaml`.
2. Matching `docker-compose*.yml|yaml` and `compose*.yml|yaml` in sorted immediate non-hidden, non-ignored directories.
3. YAML files under `k8s`, `kubernetes`, `deploy`, and `manifests`, in that directory order and sorted path order.
4. Any other YAML file under the repo, sorted path order.

Skip `.git`, `node_modules`, `vendor`, `__pycache__`, `.venv`, `venv`, `dist`, and `build`. A k8s candidate is valid only when `_file_has_workload_kind` finds a supported workload with an `apiVersion`. Compose wins whenever both formats exist.

- [ ] **Step 4: Write LLM payload conversion tests**

Add tests for `_payload_to_services` that assert a valid application service gets the repo URL as its git source, image dependencies keep their image source, env entries become a dictionary, invalid source kinds are skipped with warnings, ports outside 1–65535 become 80, and an empty usable result raises `LlmCallError` from the generation path.

Use this payload:

```python
{
    "services": [
        {
            "service_name": "web",
            "source_kind": "git",
            "source_ref": "",
            "container_port": 8000,
            "env_var_entries": [{"key": "DATABASE_URL", "value": ""}],
            "command": None,
            "public_route": True,
            "depends_on": ["db"],
        },
        {
            "service_name": "db",
            "source_kind": "image",
            "source_ref": "postgres:16",
            "container_port": 5432,
            "env_var_entries": [],
            "command": None,
            "public_route": False,
            "depends_on": None,
        },
    ],
    "summary_hint": "Web application with PostgreSQL.",
}
```

- [ ] **Step 5: Implement the repository analysis flow**

Use `_collect_context_excerpts` for the LLM fallback and `generate_json` for the stack-generation prompt. Keep the prompt explicit that repo-built services use `source_kind: "git"` and the supplied `git_url`, while external dependencies use image refs. Validate and sanitize every generated service before constructing `StackService` objects; reject blank names/source refs and invalid source kinds. Preserve the requested branch for git services.

`analyze_repo_stack` must:

1. Check `e2e_stack_repo_analysis_if_enabled` before cloning.
2. Clone with `image_builder.clone_repository(git_url, branch=git_branch, access_token=access_token)`.
3. Detect and parse the first manifest. Return `manifest_kind` and relative `manifest_path`; prepend a warning naming the selected file.
4. If a detected manifest has no services, continue to LLM generation and retain a warning.
5. Always remove the cloned parent directory in `finally`, matching `analyze_git_source`.

- [ ] **Step 6: Add API schemas, E2E fixture, and route**

Add to `backend/app/api/schemas.py`:

```python
class AnalyzeRepoRequest(BaseModel):
    git_url: str = Field(min_length=1, max_length=2048)
    git_branch: str = Field(default="main", max_length=256)


class AnalyzeRepoResponse(BaseModel):
    services: list[StackServiceCreate]
    warnings: list[str] = []
    manifest_kind: Literal["compose", "k8s", "llm"]
    manifest_path: str | None = None
    summary_hint: str | None = None
```

Add `e2e_stack_repo_analysis_if_enabled` to `backend/app/e2e_support.py`. When `VELA_E2E=1`, return a `RepoStackAnalysis` containing `web` (`nginx:alpine`, port 80, public route) and `redis` (`redis:7`, port 6379), with `manifest_kind="llm"` and a non-empty summary. Otherwise return `None`.

Add `POST /api/stacks/analyze-repo` in `backend/app/api/routes/stacks.py` before `/{stack_id}`. Resolve the GitHub token using the existing `_github_token_for_url` helper, call `analyze_repo_stack`, and convert returned ORM services using `_orm_service_to_create`.

- [ ] **Step 7: Write integration tests**

Add tests that:

```python
def test_analyze_repo_e2e_fixture(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_E2E", "1")
    response = api_client.post(
        "/api/stacks/analyze-repo",
        json={"git_url": "https://github.com/org/repo.git", "git_branch": "main"},
    )
    assert response.status_code == 200
    assert response.json()["manifest_kind"] == "llm"
    assert {s["service_name"] for s in response.json()["services"]} == {"web", "redis"}


def test_analyze_repo_no_manifest_without_llm_returns_503(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("No deployment markers.\n", encoding="utf-8")
    monkeypatch.delenv("VELA_E2E", raising=False)
    monkeypatch.delenv("VELA_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_PROJECT_ID", raising=False)
    api_client.app.dependency_overrides[get_image_builder] = lambda: StubImageBuilder(root)
    try:
        response = api_client.post(
            "/api/stacks/analyze-repo",
            json={"git_url": "https://github.com/org/repo.git", "git_branch": "main"},
        )
    finally:
        api_client.app.dependency_overrides.pop(get_image_builder, None)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
```

The stub builder's `clone_repository` returns the test root and accepts the same keyword arguments as `DefaultImageBuilder`. Add compose-found and k8s-found route tests using temporary manifests and assert `manifest_kind`, `manifest_path`, and service fields.

- [ ] **Step 8: Run backend tests**

Run: `python -m pytest tests/test_k8s_parser.py tests/test_manifest_parser.py tests/test_llm_provider.py tests/test_stack_repo_analysis.py tests -q` from `backend/`.
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/stacks/repo_analysis.py backend/app/api/schemas.py backend/app/api/routes/stacks.py backend/app/e2e_support.py backend/tests/test_stack_repo_analysis.py
git commit -m "F/stacks: analyze repositories into stack services"
```

---

### Task 5: Frontend API client and route cleanup

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/pages/stacks/ComposeImportPage.tsx`

`ComposeImportReviewModal.tsx` and `importTypes.ts` are deleted in Task 7 (Task 7 extracts the review content and removes the builder's import-seeding state first).

**Interfaces:**
- `ManifestKind = 'compose' | 'k8s'`
- `RepoManifestKind = 'compose' | 'k8s' | 'llm'`
- `parseManifest({ yaml_content }) -> ManifestParseResult`
- `analyzeRepo({ git_url, git_branch }) -> RepoAnalysisResult`

- [ ] **Step 1: Update the client types and functions**

In `frontend/src/api/client.ts`, remove `importCompose` and `parseCompose`. Add:

```typescript
export type ManifestKind = 'compose' | 'k8s'
export type RepoManifestKind = 'compose' | 'k8s' | 'llm'

export interface ManifestParseResult {
  services: StackServiceCreate[]
  warnings: string[]
  manifest_kind: ManifestKind
}

export interface RepoAnalysisResult {
  services: StackServiceCreate[]
  warnings: string[]
  manifest_kind: RepoManifestKind
  manifest_path: string | null
  summary_hint: string | null
}

export async function parseManifest(body: {
  yaml_content: string
}): Promise<ManifestParseResult> {
  return apiPost<ManifestParseResult>('/api/stacks/parse-manifest', body)
}

export async function analyzeRepo(body: {
  git_url: string
  git_branch: string
}): Promise<RepoAnalysisResult> {
  return apiPost<RepoAnalysisResult>('/api/stacks/analyze-repo', body)
}
```

- [ ] **Step 2: Remove the old import route**

In `frontend/src/App.tsx`, remove the lazy `ComposeImportPage` import and the protected `/stacks/import` route. Keep `/stacks/new` for manual creation and `/stacks/:id` for editing.

- [ ] **Step 3: Remove the obsolete import page**

Delete `frontend/src/pages/stacks/ComposeImportPage.tsx` (its only consumer, the route, was removed in Step 2). Keep `ComposeImportReviewModal.tsx` and `importTypes.ts` — Task 7 consumes them before deleting them. Confirm no other import with `rg "ComposeImportPage|/stacks/import" frontend/src frontend/e2e`.

- [ ] **Step 4: Run frontend checks**

Run: `npm run lint` from `frontend/`.
Expected: PASS after all old imports are removed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/pages/stacks/ComposeImportPage.tsx
git commit -m "F/stacks: replace compose import client flow"
```

---

### Task 6: Stacks card picker

**Files:**
- Modify: `frontend/src/pages/StacksPage.tsx`
- Create: `frontend/src/pages/stacks/stacks.css`

**Interfaces:**
- `StackCard` renders an `<article>` with a real `Link` for the name and independent Deploy/Remove buttons.
- `StackCardSkeleton` reserves the same layout while loading.

- [ ] **Step 1: Add page-specific card styles**

Create `frontend/src/pages/stacks/stacks.css` using only existing tokens. Add styles for:

```css
.stacks-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}

.stacks-card {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  min-height: 132px;
  padding: 1rem 1.1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  transition: border-color 0.15s ease;
}

.stacks-card:hover {
  border-color: var(--accent);
}

.stacks-card__top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}

.stacks-card__name {
  color: var(--text-heading);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.stacks-card__network,
.stacks-card__meta {
  color: var(--text-muted);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.stacks-card__network {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
}

.stacks-card__actions {
  display: flex;
  gap: 0.5rem;
  margin-top: auto;
}

.stacks-card--skeleton {
  pointer-events: none;
}

.stacks-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 2rem 1.5rem;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  text-align: center;
}

@media (prefers-reduced-motion: reduce) {
  .stacks-card {
    transition: none;
  }
}
```

Add skeleton-line styles and a reduced-motion rule for their pulse animation without introducing raw colors.

- [ ] **Step 2: Replace the table with cards**

In `StacksPage.tsx`, import `Link` and `./stacks/stacks.css`. Replace `StackRow` with a `StackCard` that uses `<Link to={`/stacks/${stack.id}`}>` for the stack name and retains the current Deploy/Remove callbacks. Do not wrap the card in a button or link, which would nest interactive controls.

Render four `StackCardSkeleton` articles when the initial list is loading. Render `.stacks-empty` with a short message and a New Stack button when there are no stacks. Render the card grid otherwise. Keep `loadStacks`, delete confirmation, deploy handling, and build-config recovery unchanged.

- [ ] **Step 3: Run checks**

Run: `npm run lint && npm run build` from `frontend/`.
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/StacksPage.tsx frontend/src/pages/stacks/stacks.css
git commit -m "F/stacks: replace table with card picker"
```

---

### Task 7: New Stack modal and review step

**Files:**
- Create: `frontend/src/pages/stacks/ServiceReviewStep.tsx`
- Create: `frontend/src/pages/stacks/NewStackModal.tsx`
- Modify: `frontend/src/pages/StacksPage.tsx`
- Modify: `frontend/src/pages/stacks/StackBuilderPage.tsx`
- Modify: `frontend/src/pages/stacks/stacks.css`
- Delete: `frontend/src/pages/stacks/ComposeImportReviewModal.tsx` (after extraction)
- Delete: `frontend/src/pages/stacks/importTypes.ts` (after builder cleanup)

**Interfaces:**
- `NewStackModalProps = { open: boolean; onClose: () => void; onCreated: (stackName: string) => void }`
- `ServiceReviewStepProps` includes `stackName`, `services`, `warnings`, `originLabel`, `onChangeStackName`, `onChangeServices`, `onBack`, `onCreate`, and `creating`.
- `NewStackModal` owns steps, file/repo input, async states, review data, and discard confirmation. It calls `parseManifest`, `analyzeRepo`, and `createStack`.

- [ ] **Step 1: Extract the review content into `ServiceReviewStep`**

Create `ServiceReviewStep.tsx` from the editable service rows currently in `ComposeImportReviewModal.tsx` lines 86-258. Keep fields for service name, port, source, git branch, public route, dependencies, and environment variables. Add a labeled stack-name input and an origin label. The component must not render a backdrop or attach a global Escape listener; the parent modal owns dialog behavior.

The footer has Back and Create stack buttons. Disable Create stack while `creating` and show `Creating…`. Keep every input labeled and put warnings in the existing banner classes.

- [ ] **Step 2: Write modal component tests through the existing E2E harness**

Before implementing the modal, update `frontend/e2e/stacks.spec.ts` with the expected flow:

```typescript
test('creates a stack from pasted compose in the modal', async ({ authenticatedPage }) => {
  const stackName = `e2e-modal-${Date.now()}`
  await authenticatedPage.goto('/stacks')
  await authenticatedPage.getByRole('button', { name: 'New Stack' }).click()
  const dialog = authenticatedPage.getByRole('dialog', { name: 'New Stack' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('radio', { name: /From a file/i }).click()
  await dialog.getByLabel('Stack name').fill(stackName)
  await dialog.getByLabel(/manifest content/i).fill(`
services:
  web:
    image: nginx:alpine
`)
  await dialog.getByRole('button', { name: 'Parse' }).click()
  await expect(dialog.getByText(/From .*compose/i)).toBeVisible()
  await dialog.getByRole('button', { name: 'Create stack' }).click()
  await expect(authenticatedPage.getByText(stackName)).toBeVisible()
})
```

Update the existing create test to expect a modal instead of navigation, and replace the old `/stacks/import` test with the modal flow. Assert that old Import Compose UI is absent.

- [ ] **Step 3: Implement the modal shell and source picker**

Create `NewStackModal.tsx` with a fixed backdrop and dialog matching the existing `stacks-modal` accessibility pattern: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `tabIndex={-1}`, Escape handling, focus on open, and focus restoration on close. Do not close while an async operation is active. If file text, file name, repo URL, or review data exists, route close/back through `ConfirmDialog`.

Step 1 renders a `role="radiogroup"` with three keyboard-accessible option cards. Use installed Phosphor icons (`FileText`, `GitBranch`, and `SlidersHorizontal`) with `aria-hidden="true"`. Selecting file or repo advances to step 2. Selecting Manual closes the modal and navigates to `/stacks/new`.

Show a compact progress indicator in every non-initial step, such as `Step 2 of 3 · From a repo`.

- [ ] **Step 4: Implement the file step**

The file step contains a visible stack-name label/input, a textarea labeled `Manifest content`, a hidden file input accepting `.yml,.yaml,text/yaml,application/x-yaml`, an Upload file button, Parse, and Back. Use `FileReader.readAsText`; prefill the name from the filename after removing `.yml`/`.yaml` when the name is empty. On Parse, reject empty content locally, call `parseManifest`, store services/warnings/origin, and go to review. Show API errors in an inline `role="alert"`.

- [ ] **Step 5: Implement the repo step**

The repo step contains visible Git repository URL and Git branch inputs. Validate the URL with the existing `sourceLooksLikeGitUrl` helper and default branch to `main`. Call `analyzeRepo` with `Cloning & analyzing…` while waiting. Set the default stack name from the final URL path when the name is empty. Build the origin label from the response: `From {manifest_path}`, `From Kubernetes manifests`, or `AI-generated — review carefully`.

When a 503 or configured-AI error is returned, keep the dialog open, show the error near the URL field, and render `Open manual builder`, which closes the modal and navigates to `/stacks/new`. Do not expose raw response bodies.

- [ ] **Step 6: Implement review and creation**

When review data exists, render `ServiceReviewStep`. Validate the stack name and at least one service before creation. Call `createStack({ name, services })`, show `Creating…`, then call `onCreated(name)` and close. `StacksPage` should refresh with `loadStacks()` and show `Stack '<name>' created.` as a status banner. If creation fails, leave the review step open and show the formatted API error.

Add modal-specific responsive CSS in `stacks.css`: dialog content scrolls within `max-height: min(85vh, 900px)`, source cards are one column on narrow screens and three columns on wider screens, buttons remain keyboard/touch accessible, and all motion is disabled under reduced motion.

- [ ] **Step 7: Wire the page and remove builder import state**

In `StacksPage.tsx`, add `newStackOpen` state. Make both the header and empty-state New Stack buttons open the modal. Remove the Import Compose button. Render `NewStackModal` and pass `onCreated` to refresh and set the success banner.

In `StackBuilderPage.tsx`, remove `useLocation`, `ImportedStackState`, `importSeedApplied`, and the import-seeding effect (lines ~752, ~762-781, and the `import type { ImportedStackState } from './importTypes'` import). Keep `/stacks/new` as the manual creation route and `/stacks/:id` as the edit route.

Then delete `frontend/src/pages/stacks/ComposeImportReviewModal.tsx` and `frontend/src/pages/stacks/importTypes.ts` (content extracted into `ServiceReviewStep`; seeding state removed). Verify: `rg "ComposeImport|ImportedStackState|importTypes" frontend/src frontend/e2e` returns nothing.

- [ ] **Step 8: Run frontend checks**

Run: `npm run lint && npm run build` from `frontend/`.
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/StacksPage.tsx frontend/src/pages/stacks/ServiceReviewStep.tsx frontend/src/pages/stacks/NewStackModal.tsx frontend/src/pages/stacks/StackBuilderPage.tsx frontend/src/pages/stacks/stacks.css frontend/e2e/stacks.spec.ts frontend/src/pages/stacks/ComposeImportReviewModal.tsx frontend/src/pages/stacks/importTypes.ts
git commit -m "F/stacks: add modal stack creation flow"
```

---

### Task 8: End-to-end verification and cleanup

**Files:**
- Modify: `backend/tests/test_api_integration.py`
- Modify: `backend/tests/test_stack_permissions.py`
- Modify: `frontend/e2e/stacks.spec.ts`
- Modify: `README.md` only if the environment-variable table needs the new optional Vertex settings

- [ ] **Step 1: Update backend API coverage**

Replace all test requests to `/api/stacks/parse-compose` with `/api/stacks/parse-manifest`, assert `manifest_kind == "compose"`, add a k8s parse assertion, and remove tests for deleted `/api/stacks/import-compose`. Keep RBAC coverage for create and deploy. Confirm with:

```powershell
rg "parse-compose|import-compose|ComposeImport|ImportedStackState" backend frontend
```

Expected: no production or test references remain.

- [ ] **Step 2: Update frontend E2E coverage**

Keep manual creation and deploy coverage, but locate created stacks with `.stacks-card` instead of `tr`. Add the modal compose flow from Task 7 and the E2E repo fixture flow. Assert card name, service count, modal origin text, review warnings where applicable, and success status. Do not use `page.route`.

- [ ] **Step 3: Update environment documentation if needed**

If the README documents LLM configuration, add these optional entries without including secrets:

```text
VELA_VERTEX_API_KEY
VELA_VERTEX_PROJECT_ID
VELA_VERTEX_LOCATION (default us-central1)
VELA_VERTEX_MODEL (default gemini-2.5-flash)
```

Keep the existing `VELA_GEMINI_API_KEY` and `VELA_GEMINI_MODEL` entries and state that Vertex is selected when its API key and project ID are configured; otherwise direct Gemini remains available.

- [ ] **Step 4: Run all required verification**

Run these commands exactly:

```powershell
cd backend
python -m pytest tests -q
cd ..\frontend
npm run lint
npm run build
npm run test:e2e
```

Expected: all commands exit successfully. If Playwright web servers cannot start because ports are occupied, stop the existing API/Vite processes and rerun; do not replace the live-backend E2E flow with network mocks.

- [ ] **Step 5: Review the diff**

Run:

```powershell
git status --short
git diff --check
git diff --stat
git diff
```

Check that no raw colors were added to components, no secrets are present, deleted import routes have no references, all modal controls have labels/focus states, and no unnecessary abstraction or comments were introduced.

- [ ] **Step 6: Re-verify after any cleanup**

If the diff review finds a concrete cleanup issue, fix only that issue, rerun `git diff --check`, and rerun the affected focused test or frontend check before the final verification in Step 4. Do not commit unrelated cleanup.

The implementation is complete only after the backend suite, frontend lint/build, and Playwright suite pass.
