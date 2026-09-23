# Stacks Flow Redesign: Card Picker + New Stack Modal

**Date:** 2026-08-28
**Status:** Approved

## Problem

The Stacks page is a plain table and stack creation is scattered across two full pages (`/stacks/new` builder, `/stacks/import` compose import). There is no way to create a stack from a Kubernetes manifest or from a repository that ships compose/k8s files, and the existing LLM repo analysis only pre-fills a single-container form.

## Solution

1. Replace the stack table with a **card picker** grid.
2. Replace the two create-pages with a single **New Stack modal** offering three sources:
   - **From a file** — paste/upload Docker Compose *or* Kubernetes YAML, parse, review, create.
   - **From a repo** — clone, auto-detect compose/k8s manifests and parse them; when none exist, generate the stack with an LLM. Review, create.
   - **Manual** — navigates to the existing full-page builder (unchanged).
3. Make the LLM call **provider-agnostic**: Google Vertex AI or the existing direct Gemini API, auto-detected from env vars.

Decisions made during design:

- Deterministic Kubernetes parser (not LLM-only) in this pass.
- In-modal steps ending in direct stack creation (no round-trip through the builder).
- Provider-agnostic LLM with both backends; auto-detect config, no behavior change when nothing is configured.

## Architecture

### Backend

#### `POST /api/stacks/parse-manifest` (replaces `parse-compose` and `import-compose`)

- Body: `{ yaml_content: str }` → `{ services: StackServiceCreate[], warnings: str[], manifest_kind: "compose" | "k8s" }`
- Sniffing rules (first match wins):
  1. Top-level mapping with a `services` mapping → compose (`parse_compose`).
  2. Any multi-doc YAML document with `apiVersion` + `kind` → k8s (`parse_k8s`).
  3. Neither → 400 "Unrecognized manifest — expected Docker Compose or Kubernetes YAML."

#### `app/core/stacks/k8s_parser.py`

`parse_k8s(yaml_content: str) -> tuple[list[StackService], list[str]]` — deterministic rules:

- `Deployment` / `StatefulSet` → one service each (first container only):
  - `image` → `source_kind: "image"`, `source_ref: <image>`
  - first `containerPort` → `container_port`
  - `env` list → `env_vars`
  - `command`/`args` → start command
  - name from `metadata.name`, sanitized + deduplicated like compose import
- `ConfigMap` referenced via `envFrom.configMapRef` → merged into that service's `env_vars`.
- `Ingress` → backend service names get `public_route: true`.
- Skipped with warnings: `Secret` refs, `envFrom` secret refs, `volumeMounts`, PVCs ("add manually").
- `Service` without a matching Deployment/StatefulSet → warning, ignored. Other unknown kinds → ignored.
- No `depends_on` inference (user sets it in the builder).
- No supported resources at all → 400 "No supported Kubernetes resources found (need Deployment or StatefulSet)."

#### `POST /api/stacks/analyze-repo`

- Body: `{ git_url, git_branch }` → `{ services, warnings, manifest_kind: "compose" | "k8s" | "llm" }`
- Flow:
  1. Clone via existing `DefaultImageBuilder.clone_repository` with the same GitHub-token handling as `/api/builder/analyze-source` (private repos work when the user has connected GitHub).
  2. Detect compose files: `docker-compose*.yml|yaml`, `compose*.yml|yaml` — repo root first, then top-level directories; prefer `docker-compose.yml` on ties; warning names the file used.
  3. Else detect k8s manifests: prefer files in `k8s/`, `kubernetes/`, `deploy/`, `manifests/` directories, else any repo YAML (excluding `.git`, `node_modules`) with supported kinds; warning names the file used.
  4. Else (no manifests in the repo) → LLM stack generation (below). If no LLM provider is configured → 503 "AI analysis is not configured on this server."
- E2E: fixture hook in `backend/app/e2e_support.py` (`e2e_stack_repo_analysis_if_enabled(git_url, git_branch)`), same pattern as `e2e_git_source_analysis_if_enabled`, so tests run without cloning or an LLM.

#### Shared LLM module `app/core/llm/`

Extracted from `app/core/git/git_source_analysis.py`; provider-agnostic.

- `async generate_json(*, prompt: str, context: str, schema: dict) -> dict` — httpx call with `responseMimeType: application/json` + `responseSchema`, parses the JSON text out of the response, maps failures to `GitSourceAnalysisError`-style domain errors (log detail server-side, generic message client-side).
- Provider resolution (auto-detect, first match):
  1. `VELA_VERTEX_API_KEY` **and** `VELA_VERTEX_PROJECT_ID` set (location from `VELA_VERTEX_LOCATION`, default `us-central1`) → **Vertex**: `https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent`, auth header `x-goog-api-key`, model from `VELA_VERTEX_MODEL` (default `gemini-2.5-flash`).
  2. `VELA_GEMINI_API_KEY` → **Gemini** (current behavior, `VELA_GEMINI_MODEL` default `gemini-2.0-flash`).
  3. Neither → `None`; callers keep their deterministic fallbacks.
- The existing single-container analysis (`git_source_analysis.py`) keeps its prompt/schema/fallback logic; only the transport call moves into the shared module.

#### LLM stack generation (new prompt + schema)

- Input: repo file excerpts (README, dependency manifests, env example files) — reuse the excerpt collection already in `git_source_analysis.py`.
- Output schema:
  ```json
  {
    "services": [{
      "service_name": "string",
      "source_kind": "image | git",
      "source_ref": "image ref OR the repo git URL",
      "container_port": 0,
      "env_vars": {"KEY": "value"},
      "command": ["tokens"] | null,
      "public_route": false,
      "depends_on": ["other-service"]
    }],
    "summary_hint": "one short sentence for the UI"
  }
  ```
- Services built *from the repo* use `source_kind: "git"` with `source_ref` = repo URL (build config can be supplied later via the existing `needs_build_override` deploy flow). External dependencies (Postgres, Redis, …) use image refs.
- No provider configured or call/parse failure → 503 "AI analysis is not configured on this server." / "Could not complete AI analysis. Try again or create manually."

### Frontend

#### Card picker (`StacksPage.tsx`)

- Grid: `repeat(auto-fill, minmax(280px, 1fr))`, 16px gap.
- Card: name (clickable → `/stacks/:id` edit), network in mono, meta line (`3 services · Aug 12`), footer actions **Deploy** and **Remove** (keeps the existing two-step "Confirm?" pattern; deploy failure still opens the build-config modal exactly as today).
- A11y: card is an `<article>`; the name is the real focusable link (no nested buttons); `:focus-visible` ring; hover = border accent + cursor pointer; all actions reachable by tap and keyboard.
- Loading: skeleton cards mirroring the final layout (stable heights).
- Empty state: short message + **New Stack** primary button.
- The **New Stack** button opens the modal (was: navigate to `/stacks/new`). The **Import Compose** button is removed.

#### `NewStackModal` (multi-step, reuses the `stacks-modal` shell)

Header shows a step indicator ("2 of 3 · From a repo") and a back button; Escape closes (with discard confirm when content is entered, reusing the existing `ConfirmDialog` pattern).

1. **Choose source** — three selectable option cards (radiogroup semantics, Phosphor icons, `aria-hidden` on decorative icons):
   - *From a file* — "Docker Compose or Kubernetes YAML. Paste or upload."
   - *From a repo* — "Vela detects Compose or K8s manifests; if none, AI builds the stack."
   - *Manual* — "Define services yourself in the builder." → navigates to `/stacks/new` immediately.
2. **Prepare**
   - File path: stack name input (pre-filled from filename) + textarea + **Upload file** button (existing `FileReader` pattern) → **Parse** (disabled while parsing, label "Parsing…").
   - Repo path: git URL input (validated with the existing `sourceLooksLikeGitUrl`) + branch input (default `main`) → **Analyze repo**, waiting label "Cloning & analyzing… takes a few seconds."
   - Errors render inline under the offending field (`role="alert"`); buttons disabled while working.
3. **Review** — the existing review layout (editable service rows: name, port, source, env vars; warnings banner) plus an origin badge: "From `docker-compose.yml`" / "From `k8s/deploy.yaml`" / "AI-generated — review carefully". Stack name input at top. **Create stack** (loading "Creating…") → `createStack` → modal closes, grid refreshes, success banner (`role="status"`).
- AI unavailable (503): error in step 2 + **Open manual builder** button (navigates to `/stacks/new`).

#### Removed (logic folded into the modal)

- `frontend/src/pages/stacks/ComposeImportPage.tsx` + `/stacks/import` route in `App.tsx`
- `ComposeImportReviewModal.tsx` (inner content becomes the modal's review step component)
- `parseCompose` / `importCompose` client functions (replaced by `parseManifest`, `analyzeRepo`)
- `ImportedStackState` builder-seeding state in `StackBuilderPage` (import no longer seeds the builder)
- Backend `POST /api/stacks/parse-compose` and `POST /api/stacks/import-compose` endpoints

#### Styling

- All colors from existing `:root` tokens in `index.css` (no raw hex).
- New page-specific styles in a separate CSS file imported by the page (do not grow `index.css`).
- Motion respects the existing `prefers-reduced-motion: reduce` block.

## Error handling (client-facing messages)

| Failure | Response | UI |
|---|---|---|
| Unrecognizable manifest file | 400 "Unrecognized manifest — expected Docker Compose or Kubernetes YAML." | Inline under textarea |
| K8s file, no supported resources | 400 "No supported Kubernetes resources found (need Deployment or StatefulSet)." | Same |
| Clone failed (bad URL/branch/private without token) | 400 with mapped message (reuses existing clone error mapping) | Inline under URL field |
| Repo has no compose/k8s, no LLM configured | 503 "AI analysis is not configured on this server." | Error + **Open manual builder** |
| LLM call failed / bad JSON | 503 "Could not complete AI analysis. Try again or create manually." | Same |
| Create fails (name clash, validation) | Existing stack error mapping | Banner in review step |

Deploy-time build-config flow for git-source services is unchanged (existing `needs_build_override` handling).

## Testing

- **Backend pytest** (`cd backend && python -m pytest tests -q`):
  - `k8s_parser` unit: multi-doc fixture (Deployment + Service + ConfigMap + Ingress + Secret envFrom) asserting image/port/env merge/`public_route` from Ingress/warnings for Secret.
  - `parse-manifest` integration: compose content → compose services, k8s content → k8s services, garbage → 400.
  - `analyze-repo` integration via the E2E fixture hook: compose-found, k8s-found, none+no-LLM → 503.
  - LLM provider resolution unit: vertex vars → vertex, gemini key → gemini, nothing → None.
- **Playwright E2E** (`cd frontend && npm run test:e2e`):
  - Modal file path: open modal → paste compose YAML → parse → review → create → card appears in grid.
  - Modal repo path: seeded E2E fixture → create → card appears.
  - No `page.route` mocking for app flows (repo rule).
- Both suites must pass before the work is considered complete (AGENTS.md verification rule).

## Out of scope

- Helm charts, additional manifest formats (k8s + compose only, per decision).
- Service-account OAuth for Vertex (personal API key only; service account is a later follow-up if needed).
- Editing existing stacks (builder page unchanged).
- `depends_on` inference in the k8s parser.
