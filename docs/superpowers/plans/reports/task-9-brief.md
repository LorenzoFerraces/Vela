### Task 9: Wire Stacks builder + list deploy

**Files:**
- Modify: `frontend/src/pages/stacks/StackBuilderPage.tsx`
- Modify: `frontend/src/pages/stacks/ComposeImportReviewModal.tsx` (optional display)
- Modify stacks list deploy handler (find the page that calls deploy)
- Modify: `frontend/src/api/client.ts` stack types if build_override missing on StackService

**Behavior:**
- Git service can open BuildConfigModal and set `build_override`
- Persist via create/update stack
- List deploy: on `needs_build_override`, open modal for failing service (parse name from detail if present), PATCH/update override, redeploy

Preserve existing Close button / git_branch UI if already in StackBuilderPage WIP.

- [ ] **Step 1: Implement**
- [ ] **Step 2: `npm run build` passes**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: stacks persist and prompt for per-service build overrides"
```
