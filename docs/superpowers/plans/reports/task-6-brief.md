### Task 6: API schemas, error handler, analyze enrichment, route wiring

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/errors.py`
- Modify: `backend/app/api/routes/builder.py` (if needed)
- Modify: `backend/app/api/routes/containers.py`
- Modify: `backend/app/api/routes/stacks.py`
- Modify: `backend/app/core/git/git_source_analysis.py`
- Modify: `backend/app/core/deploy/deployment_history.py`
- Test: `backend/tests/test_api_integration.py` (new cases)

**Interfaces:**
- `GitSourceAnalysis.needs_manual_build_config: bool = False`
- `GitSourceAnalysis.build_subdir: str | None = None`
- `RunFromSourceRequest.build_override` optional
- `StackServiceCreate` / `StackServicePublic` include `build_override`
- HTTP 422 with `{"code":"needs_build_override","detail":"..."}` via dedicated NeedsBuildOverrideError handler

- [ ] **Step 1: Failing API test — stack create persists build_override**

```python
def test_stack_create_persists_build_override(api_client):
    body = {
        "name": "ovr",
        "services": [{
            "service_name": "app",
            "source_kind": "git",
            "source_ref": "https://github.com/example/app.git",
            "git_branch": "main",
            "build_override": {"language": "java", "package_manager": "gradle"},
        }],
    }
    resp = api_client.post("/api/stacks/", json=body)
    assert resp.status_code == 201
    assert resp.json()["services"][0]["build_override"]["language"] == "java"
```

- [ ] **Step 2: Implement schema fields + ORM mapping in stacks create/update/`_stack_to_public`**

Note: schemas.py / stacks.py may have uncommitted git_branch WIP — carefully merge build_override without discarding git_branch if present in working tree. Prefer including both if both are WIP.

- [ ] **Step 3: Exception handler for NeedsBuildOverrideError** returning api_response_content()

- [ ] **Step 4: Containers run** passes body.build_override into build_from_source and stores on DeploymentRecord

- [ ] **Step 5: Tests PASS + commit**

```bash
git commit -m "feat: API support for build overrides and needs_build_override errors"
```

Commit ONLY backend API/core/test files for this task. No frontend.
