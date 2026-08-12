### Task 7: Frontend types + shared BuildConfigModal

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/containers/BuildConfigModal.tsx`
- Create: `frontend/src/pages/containers/buildOverride.ts`
- Modify: `frontend/src/index.css` (reuse compose-import modal patterns)

**Interfaces:**
- `BuildOverride` TS type matching backend
- `isNeedsBuildOverrideError(err: unknown): boolean` via `code` field on API error
- `<BuildConfigModal open onCancel onConfirm(override) initial? />`
- Language options: python, javascript, typescript, go, java, rust, ruby, php, dotnet, elixir, clojure
- Package manager select when language is java (gradle|maven), javascript/typescript (npm|pnpm|yarn), clojure (deps|lein)
- Optional version, subdir, start command

- [ ] **Step 1: Implement modal** following existing modal CSS (ComposeImportReviewModal / stacks-modal patterns)
- [ ] **Step 2: `npm run build` (tsc) from frontend/ passes**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: shared BuildConfigModal for manual language overrides"
```

client.ts may have uncommitted stack git_branch types — preserve them; add BuildOverride types carefully. Stage only Task 7 files (+ needed client.ts hunks). No ContainersPage/Stacks wiring yet (Tasks 8–9).
