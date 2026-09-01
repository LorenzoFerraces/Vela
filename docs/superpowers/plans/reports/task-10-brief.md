### Task 10: E2E coverage

**Files:**
- Create: `frontend/e2e/build-override.spec.ts`
- Extend `backend/app/e2e_support.py` if needed to stub analyze / accept override without flaky GitHub

**Scenario:**
1. Login as E2E user (credentials from frontend/e2e/constants.ts — stay in sync with backend e2e_support)
2. Hit path that yields needs_manual_build_config or needs_build_override
3. Modal → select Java / Gradle → confirm
4. Assert override saved and/or deploy succeeds under fake orchestrator

Prefer E2E stubs over real GitHub. Follow existing stacks.spec.ts patterns. No page.route mocking for app API flows except external systems.

- [ ] **Step 1: Write spec**
- [ ] **Step 2: `cd frontend && npm run test:e2e -- e2e/build-override.spec.ts` PASS**
- [ ] **Step 3: Commit**

```bash
git commit -m "test: e2e for build override modal on stacks/containers"
```
