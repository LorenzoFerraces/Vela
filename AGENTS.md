# Agent rules (Vela)

Conventions for tooling, dependencies, naming, and Python style. Follow this file when changing the repo.

## Package management (pnpm / npm)

- **Do not introduce caret (`^`) or tilde (`~`) ranges** when adding or updating dependencies in `package.json`. Prefer **exact versions** (e.g. `"18.2.0"`, not `"^18.2.0"`).
- **pnpm**: If the project uses pnpm, treat `save-exact` as mandatory behavior: new dependencies must be pinned. Do not rely on loose semver in `package.json`.
- **Configuration**: The repo keeps a root-level policy in `frontend/.npmrc` so installs default to exact saves. After adding a dependency, verify `package.json` has **no** `^` / `~` on that entry.

## `.npmrc`

- `frontend/.npmrc` sets `save-exact=true` so **new dependencies are saved without `^` automatically** (for npm and pnpm in this directory).
- Do not remove `save-exact=true` without team agreement.

## Variable and identifier naming

- Use **clear, full words** for variables, functions, and parameters (e.g. `container_id`, `request_body`, `orchestrator`).
- **Avoid** cryptic abbreviations and **single-letter** names except where idiomatic and extremely local (e.g. short loop index in a comprehension is acceptable; a function parameter named `x` or `c` is not).

## Python

- Prefer the **most idiomatic (“Pythonic”)** style: explicit is better than implicit; use standard library and typing where it helps clarity; follow existing project patterns (imports at top of file, structured errors, `match`/`case` for exhaustiveness on unions when appropriate).
- Match surrounding modules for layout, naming, and error handling unless you are deliberately standardizing a new pattern (then document it here in a short note).

## Backend structure (MVC)

Keep new and refactored code aligned with this separation of concerns under `backend/app/`:

- **Model** (`app/core/`): Domain logic, orchestration, and integrations (e.g. Docker, routing helpers). Core modules should not own HTTP wiring; they expose functions or types the API layer calls.
- **View** (API presentation): Request and response shapes and serialization — e.g. `app/api/schemas.py` and any route-local response models. This is the contract the client sees.
- **Controller** (`app/api/routes/`, `app.py`, `deps.py`): Thin HTTP handlers — parse and validate input, call into `app/core/`, map domain errors to HTTP responses, return view models. Avoid embedding heavy business logic in route functions.

When adding a feature, place logic in the right layer instead of growing “god” route modules.

## Backend testing

- **Core functionality** (auth, container ownership, orchestration boundaries, and other user-visible or safety-critical behavior) should be covered by **integration tests** in `backend/tests/` — typically exercising HTTP routes and real-ish wiring (e.g. `TestClient`, DB overrides where the suite uses SQLite, Docker mocks as the project already does).
- **Model / unit tests** for pure domain helpers (e.g. `app/core/` without HTTP) are **optional** but encouraged when logic is non-trivial, easy to isolate, and cheaper to test than a full API path.

## Cleaning AI-generated changes (deslop)

After substantive agent-generated edits on a branch, run the **deslop** Cursor skill on the diff: remove unnecessary comments, abnormal defensive `try`/`except` on trusted paths, `any` casts used only to silence types, and deeply nested structure that does not match surrounding code — **without changing behavior** except for clear bugs. Prefer small, focused cleanups over broad rewrites.

## TypeScript / React (frontend)

- **Avoid `instanceof` when practical.** Prefer discriminated unions, narrow with `typeof` / `in`, small type-predicate helpers, or parsing/validation (e.g. Zod) so behavior does not depend on prototype chains or cross-realm objects.
- Use `instanceof` only where it is clearly the best tool (e.g. a well-owned `Error` subclass in the same bundle) and document why if it is non-obvious.

## UI and forms (user experience)

- **Prioritize user experience** when designing and building interfaces: flows should feel clear, fast, and respectful of attention.
- **Follow common UX patterns** where they apply: clear navigation and hierarchy, visible loading and success/error feedback, sensible empty states, destructive actions behind confirmation, keyboard-friendly controls where the rest of the app does the same. Stay consistent with existing pages in this repo before introducing a new interaction model.
- **When usability or user flow is unclear** (e.g. multi-step flows, dense data, unfamiliar domain), ask for product or design guidance or propose **short** options in chat instead of guessing a one-off pattern.
- **Keep form fields short and concise** (labels, placeholders, helper text). Prefer tight copy over verbose prose.
- **Avoid long explanations** inline on the form; if something needs detail, link to docs or a collapsible help pattern rather than wall-of-text above fields.
- **Long forms are fine to split**: use **multi-step flows** or **modals** (and related patterns) so users are not overwhelmed by a single scrolling page of inputs.
- **Containers** (`frontend/src/pages/ContainersPage.tsx`): the run form always uses **public routes** (`public_route: true`), fixed **container port 80**, no host port mapping, and shows **Git branch** only when the source looks like a Git URL (same `git@` / `http(s)://` / `ssh://` prefix rules as `POST /api/containers/run` on the server).

## Errors shown to users (frontend and API)

- **Surface client-facing messages**, not raw implementation details. Do not let low-level or library errors reach the UI unchanged when a clearer explanation is possible.
- **Frontend**: On failure, show a short, actionable string (e.g. from API `detail` or a mapped message). Avoid re-throwing or logging-only flows that leave the user with a generic “Something went wrong” or a stack trace in production UI.
- **Backend**: Prefer structured HTTP errors (`detail`, optional fields) from domain exceptions; avoid leaking stack traces or internal identifiers in normal error responses. Map unexpected failures to a safe generic message when appropriate.
