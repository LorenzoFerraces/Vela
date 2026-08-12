### Task 4: Image builder + stack deploy pass override / build_subdir

**Files:**
- Modify: `backend/app/core/build/builder.py` (protocol signature if needed)
- Modify: `backend/app/core/build/default_image_builder.py`
- Modify: `backend/app/core/stacks/deploy.py`
- Update any Fake image builder used in tests
- Test: `backend/tests/test_default_image_builder_override.py`

**Interfaces:**
- Produces: `build_from_source(..., override: BuildOverride | None = None)`
- Build context path must be the effective subdirectory when `build_subdir` is set
- Stack deploy reads `service.build_override` JSON into `BuildOverride`

- [ ] **Step 1: Write failing test** that nested marker yields `build_image` called with `.../backend` path

- [ ] **Step 2: Implement wiring**

```python
strategy, info = ensure_dockerfile_for_build(
    Path(project_path),
    from_git_clone=source.git_url is not None,
    override=override,
)
build_root = Path(project_path)
if info.build_subdir:
    candidate = (build_root / info.build_subdir).resolve()
    if not candidate.is_relative_to(build_root.resolve()):
        raise AnalysisError(str(build_root), "invalid build_subdir")
    build_root = candidate
image_id = await self._orchestrator.build_image(
    str(build_root), tag=tag, dockerfile="Dockerfile"
)
```

In `deploy.py`, parse `service.build_override` → `BuildOverride` and pass through.

- [ ] **Step 3: Tests PASS + commit**

```bash
git commit -m "feat: honor build override and subdir in image builds"
```
