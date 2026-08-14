### Task 8: Wire Containers run + analyze flow

**Files:**
- Modify: `frontend/src/pages/ContainersPage.tsx`
- Modify: `frontend/src/pages/containers/useGitSourceAnalysis.ts`
- Modify related run form state as needed

**Behavior:**
- Keep `buildOverride` in run form state
- After analyze: if `needs_manual_build_config`, open BuildConfigModal; on confirm set override
- On run failure: if `isNeedsBuildOverrideError`, open modal; on confirm set override and optionally auto-retry run
- Include `build_override` in runFromSource / run payload

Use existing BuildConfigModal from Task 7.

- [ ] **Step 1: Implement**
- [ ] **Step 2: Commit**

```bash
git commit -m "feat: containers flow prompts for build override when needed"
```

`npm run build` should still pass. Do not rewrite Stacks (Task 9).
