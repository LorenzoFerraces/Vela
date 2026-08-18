# Resource Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose CPU and memory limits on the container run/deploy form so users can constrain container resources.

**Architecture:** Wire existing `DeployConfig.cpu_limit` and `DeployConfig.memory_limit` through `RunFromSourceRequest` schema, deploy route, and frontend form.

**Tech Stack:** FastAPI, Pydantic v2, React, TypeScript

## Corrections (2026-08-16 review)

- **Unit bug:** `DockerOrchestrator.deploy` passed `config.memory_limit` straight to docker-py `mem_limit`, which treats numbers as **bytes**. `memory_limit` is documented as MB everywhere, so 256 (MB) became 256 bytes → instant OOM kill. Fix (Task 2.4): convert MB→bytes at the single orchestrator call site and document the unit (`gt=0`) on `DeployConfig`.
- `RunFromSourceRequest` fields are added after `build_override` (not `scaling_policy`); the 3 `_deploy_config_for_image` call sites are at lines ~697/~751/~824 in `routes/containers.py`.
- Pair with `2025-08-03-resource-dashboard.md` for per-user/team usage visibility (`GET /api/metrics/usage`). Quota enforcement (hard ceilings at deploy time) is deliberately out of scope — add when a product policy exists.

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~)
- Backend MVC: core/ (domain), schemas.py (views), routes/ (controllers)
- TDD: write failing test first, then minimal implementation
- Follow existing code style: explicit, typed, match surrounding modules

---

## Task 1: Add `cpu_limit` and `memory_limit` to `RunFromSourceRequest` schema

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/test_api_integration.py`

**Interfaces:**
- Consumes: Existing `DeployConfig` model with `cpu_limit: float | None`, `memory_limit: int | None`
- Produces: `RunFromSourceRequest` with two new optional fields

### Step 1.1: Write a failing test for the new schema fields

File: `backend/tests/test_api_integration.py`

Add these two tests after `test_run_from_image_with_env_and_command` (line ~217):

```python
def test_run_from_image_with_resource_limits(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "cpu_limit": 0.5,
            "memory_limit": 256,
        },
    )
    assert response.status_code == 200
    assert fake_orchestrator.last_deploy_config is not None
    assert fake_orchestrator.last_deploy_config.cpu_limit == 0.5
    assert fake_orchestrator.last_deploy_config.memory_limit == 256


def test_run_from_image_resource_limits_optional(api_client: TestClient) -> None:
    """Omitting resource limits should still work (fields are optional)."""
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
        },
    )
    assert response.status_code == 200
```

- [ ] Write the two test functions to `backend/tests/test_api_integration.py`
- [ ] Run `cd backend && python -m pytest tests/test_api_integration.py::test_run_from_image_with_resource_limits tests/test_api_integration.py::test_run_from_image_resource_limits_optional -q` — expect first test to fail (422 or field ignored), second to pass

### Step 1.2: Add fields to `RunFromSourceRequest`

File: `backend/app/api/schemas.py`

After the `build_override` field (line ~168; the last declared field of
`RunFromSourceRequest`, right before the validators), add:

```python
    cpu_limit: float | None = Field(
        default=None,
        gt=0,
        description="CPU limit in cores (e.g. 0.5 for half a core).",
    )
    memory_limit: int | None = Field(
        default=None,
        gt=0,
        description="Memory limit in MB.",
    )
```

- [ ] Add the two fields to `RunFromSourceRequest` in `backend/app/api/schemas.py`
- [ ] Run the two tests again — both should pass
- [ ] Run full test suite: `cd backend && python -m pytest tests -q` — ensure no regressions

---

## Task 2: Wire resource limits through the deploy route

**Files:**
- Modify: `backend/app/api/routes/containers.py`
- Modify: `backend/tests/test_api_integration.py`

**Interfaces:**
- Consumes: `RunFromSourceRequest.cpu_limit`, `RunFromSourceRequest.memory_limit`
- Produces: `DeployConfig` with `cpu_limit` and `memory_limit` set

### Step 2.1: Write a failing test for the route wiring

File: `backend/tests/test_api_integration.py`

Add this test after the Task 1 tests:

```python
def test_run_resource_limits_pass_through_all_source_kinds(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    """cpu_limit and memory_limit from RunFromSourceRequest reach DeployConfig."""
    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "cpu_limit": 1.0,
            "memory_limit": 512,
        },
    )
    assert response.status_code == 200
    cfg = fake_orchestrator.last_deploy_config
    assert cfg is not None
    assert cfg.cpu_limit == 1.0
    assert cfg.memory_limit == 512
```

- [ ] Add the test to `backend/tests/test_api_integration.py`
- [ ] Run the test — expect failure (limits not passed through)

### Step 2.2: Update `_deploy_config_for_image` to accept resource limits

File: `backend/app/api/routes/containers.py`

Update the function signature (line ~260) and body:

```python
def _deploy_config_for_image(
    *,
    image: str,
    container_name: str | None,
    host_port: int | None,
    container_port: int,
    env_vars: dict[str, str] | None = None,
    command: list[str] | None = None,
    volumes: list[VolumeMount] | None = None,
    cpu_limit: float | None = None,
    memory_limit: int | None = None,
) -> DeployConfig:
    ports: list[PortMapping] = []
    if host_port is not None:
        ports.append(PortMapping(host_port=host_port, container_port=container_port))
    return DeployConfig(
        image=image,
        name=container_name,
        ports=ports,
        container_listen_port=container_port,
        env_vars=env_vars or {},
        command=command,
        volumes=volumes or [],
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        health_check=default_listen_port_health_check(container_port),
    )
```

- [ ] Update `_deploy_config_for_image` signature and return statement
- [ ] Run the test — still fails (callers haven't been updated yet)

### Step 2.3: Pass limits from `run_from_user_source` callers

File: `backend/app/api/routes/containers.py`

There are three `_deploy_config_for_image` calls in `run_from_user_source`:

1. **Image deploy** (line ~694): Add `cpu_limit=body.cpu_limit, memory_limit=body.memory_limit`
2. **Dockerfile template deploy** (line ~748): Same
3. **Git deploy** (line ~820): Same

For the image deploy block (lines 694-702), change:
```python
        cfg = _deploy_config_for_image(
            image=image_ref,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
            env_vars=body.env_vars,
            command=body.command,
            volumes=resolved_volumes,
        )
```
to:
```python
        cfg = _deploy_config_for_image(
            image=image_ref,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
            env_vars=body.env_vars,
            command=body.command,
            volumes=resolved_volumes,
            cpu_limit=body.cpu_limit,
            memory_limit=body.memory_limit,
        )
```

Apply the same `cpu_limit=body.cpu_limit, memory_limit=body.memory_limit` addition to the dockerfile_template call (line ~748) and the git call (line ~820).

- [ ] Update all three `_deploy_config_for_image` calls in `run_from_user_source`
- [ ] Run the test — expect pass
- [ ] Run full test suite: `cd backend && python -m pytest tests -q`

### Step 2.4: Fix the MB→bytes unit bug in the Docker orchestrator

File: `backend/app/core/containers/docker_orchestrator.py`

In `deploy()` the limit is forwarded raw: `kwargs["mem_limit"] = config.memory_limit`. docker-py treats numeric `mem_limit` as **bytes**, so an MB value is off by a factor of 1048576 (256 "MB" → 256 bytes → instant OOM kill). Change to:

```python
            if config.memory_limit is not None:
                kwargs["mem_limit"] = config.memory_limit * 1024 * 1024
```

And document the unit on `DeployConfig` in `backend/app/core/models.py`:

```python
    cpu_limit: float | None = Field(
        default=None, gt=0, description="CPU limit in cores (e.g. 0.5 for half a core)."
    )
    memory_limit: int | None = Field(
        default=None, gt=0, description="Memory limit in MB."
    )
```

`gt=0` also covers the direct `POST /api/containers/deploy` path, which takes `DeployConfig` unmediated.

- [ ] Apply both edits
- [ ] Run full test suite: `cd backend && python -m pytest tests -q`

---

## Task 3: Frontend — add resource limit fields to the run form

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/containers/ContainersRunAdvancedFields.tsx`
- Modify: `frontend/src/pages/ContainersPage.tsx`

**Interfaces:**
- Consumes: User input for CPU cores (float) and memory MB (int)
- Produces: `RunFromSourceRequest` with `cpu_limit` and `memory_limit` populated

### Step 3.1: Add fields to the TypeScript `RunFromSourceRequest` interface

File: `frontend/src/api/client.ts`

After `build_override` (line ~457; the last field of the interface), add:

```typescript
  cpu_limit?: number | null
  memory_limit?: number | null
```

- [ ] Add the two optional fields to `RunFromSourceRequest` interface
- [ ] Run `cd frontend && npm run build` — expect success

### Step 3.2: Add resource limit inputs to `ContainersRunAdvancedFields`

File: `frontend/src/pages/containers/ContainersRunAdvancedFields.tsx`

Add two new props to `ContainersRunAdvancedFieldsProps` (line ~18):

```typescript
  cpuLimit: string
  onCpuLimitChange: (value: string) => void
  memoryLimit: string
  onMemoryLimitChange: (value: string) => void
```

Destructure them in the component function (after `scalingValidationError`):

```typescript
  cpuLimit,
  onCpuLimitChange,
  memoryLimit,
  onMemoryLimitChange,
```

Add the input fields before the `ContainersRunScalingFields` component (before line ~290):

```tsx
          <label className="containers-form__label" htmlFor="cpu-limit-input">
            CPU limit (cores)
          </label>
          <input
            id="cpu-limit-input"
            className="containers-form__input"
            type="number"
            step="0.1"
            min="0.1"
            placeholder="e.g. 0.5"
            value={cpuLimit}
            onChange={(event) => onCpuLimitChange(event.target.value)}
          />
          <p className="containers-muted containers-form__hint">
            Maximum CPU cores the container can use. Leave empty for no limit.
          </p>

          <label className="containers-form__label" htmlFor="memory-limit-input">
            Memory limit (MB)
          </label>
          <input
            id="memory-limit-input"
            className="containers-form__input"
            type="number"
            step="1"
            min="1"
            placeholder="e.g. 256"
            value={memoryLimit}
            onChange={(event) => onMemoryLimitChange(event.target.value)}
          />
          <p className="containers-muted containers-form__hint">
            Maximum memory in megabytes. Leave empty for no limit.
          </p>
```

- [ ] Add props, destructuring, and input fields to `ContainersRunAdvancedFields.tsx`
- [ ] Run `cd frontend && npm run build` — expect success

### Step 3.3: Wire state in `ContainersPage`

File: `frontend/src/pages/ContainersPage.tsx`

Add state (after `scalingPolicy`, line ~48):

```typescript
  const [cpuLimit, setCpuLimit] = useState('')
  const [memoryLimit, setMemoryLimit] = useState('')
```

Reset in `resetAdvancedFields` (after `setScalingPolicy(null)`, line ~92):

```typescript
    setCpuLimit('')
    setMemoryLimit('')
```

Parse and include in `buildRunRequest` (in the `base` object, after
`build_override`):

```typescript
      cpu_limit: cpuLimit.trim() ? parseFloat(cpuLimit.trim()) : null,
      memory_limit: memoryLimit.trim() ? parseInt(memoryLimit.trim(), 10) : null,
```

Pass props to `<ContainersRunAdvancedFields>` (find the existing usage and add):

```tsx
          cpuLimit={cpuLimit}
          onCpuLimitChange={setCpuLimit}
          memoryLimit={memoryLimit}
          onMemoryLimitChange={setMemoryLimit}
```

- [ ] Add state, reset logic, request parsing, and prop wiring to `ContainersPage.tsx`
- [ ] Run `cd frontend && npm run build` — expect success
- [ ] Run `cd frontend && npm run lint` — expect success

---

## Task 4: E2E verification

**Files:**
- Modify: `frontend/e2e/containers.spec.ts`

### Step 4.1: Extend the advanced-options test with the limit fields

In `test('advanced env and start command can be set before build')`
(after the "Advanced options" click, line ~82), assert the new fields exist
and submit a deploy with them (no backend state is reachable from E2E beyond
the HTTP round-trip, so visible fields + successful deploy is the assertion):

```typescript
    await expect(
      authenticatedPage.getByLabel('CPU limit (cores)'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('Memory limit (MB)'),
    ).toBeVisible()
    await authenticatedPage.getByLabel('CPU limit (cores)').fill('0.5')
    await authenticatedPage.getByLabel('Memory limit (MB)').fill('128')
```

The existing `Build` click and "Started" alert assertion already cover the
submit path with limits included in the request.

### Step 4.2: Run the suite

- [ ] Run `cd frontend && npm run test:e2e` — expect all tests to pass
  (stop dev servers on ports 8000/5173 first; `reuseExistingServer` is off)
- [ ] Manual smoke: open the containers page, expand "Advanced options",
  confirm both fields accept input and reset after a successful deploy

---

## Self-Review

### Spec coverage
- [x] `RunFromSourceRequest` schema has `cpu_limit` and `memory_limit` (Task 1)
- [x] Deploy route passes them through to `DeployConfig` (Task 2)
- [x] Frontend form exposes the fields in the advanced section (Task 3)
- [x] Tests cover schema acceptance and route passthrough (Tasks 1-2)
- [x] Docker orchestrator already applies both limits; the only change is the MB→bytes conversion and unit docs (Task 2.4)

### Placeholder scan
- No "TBD", "TODO", or "add validation" placeholders remain
- All code snippets are complete and ready to paste

### Type consistency
- Backend: `cpu_limit: float | None`, `memory_limit: int | None` matches `DeployConfig`
- Frontend: `cpu_limit?: number | null`, `memory_limit?: number | null` matches Pydantic optional-nullable pattern
- Pydantic `gt=0` validators ensure positive values when provided
- Frontend parses to `null` when empty string, matching the optional-nullable pattern

### Boundary notes
- The `POST /deploy` endpoint accepts `DeployConfig` directly and already supports `cpu_limit`/`memory_limit` — no changes needed there
- The `FakeContainerOrchestrator.deploy()` stores `last_deploy_config` as-is, so tests can assert on the config without Docker
