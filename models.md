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

## TypeScript / React (frontend)

- **Avoid `instanceof` when practical.** Prefer discriminated unions, narrow with `typeof` / `in`, small type-predicate helpers, or parsing/validation (e.g. Zod) so behavior does not depend on prototype chains or cross-realm objects.
- Use `instanceof` only where it is clearly the best tool (e.g. a well-owned `Error` subclass in the same bundle) and document why if it is non-obvious.

## Errors shown to users (frontend and API)

- **Surface client-facing messages**, not raw implementation details. Do not let low-level or library errors reach the UI unchanged when a clearer explanation is possible.
- **Frontend**: On failure, show a short, actionable string (e.g. from API `detail` or a mapped message). Avoid re-throwing or logging-only flows that leave the user with a generic “Something went wrong” or a stack trace in production UI.
- **Backend**: Prefer structured HTTP errors (`detail`, optional fields) from domain exceptions; avoid leaking stack traces or internal identifiers in normal error responses. Map unexpected failures to a safe generic message when appropriate.
