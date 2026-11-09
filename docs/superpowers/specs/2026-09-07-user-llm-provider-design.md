# User LLM Provider (BYO Key): OpenAI-Compatible, Gemini, Anthropic

**Date:** 2026-09-07
**Status:** Approved

## Problem

Vela's two AI features (git source analysis for the container run form, and stack repo analysis) use only the server operator's LLM, configured via env vars (`VELA_GEMINI_API_KEY`, Vertex vars) with a Gemini wire format. Users cannot bring their own key, cannot use a model the operator didn't configure, and on servers where no LLM is configured the AI features are simply unavailable (`503`).

## Solution

Let each user save **one active LLM provider** in their Vela account. When an AI feature runs, the user's provider is used if present; otherwise the server default applies (existing behavior, unchanged).

Supported user providers:

- **OpenAI-compatible** — any endpoint speaking `POST /chat/completions` (OpenAI, OpenRouter, Groq, vLLM, LM Studio, Ollama-with-proxy, …). User supplies base URL + API key + model.
- **Gemini** — user's own Google API key (same wire format the server already speaks).
- **Anthropic** — Messages API, user's key + model name.

Decisions made during design:

- Provider class registry (abstract `LlmProvider` + 3 implementations) rather than a match-on-enum in one module — providers will grow (auth schemes, listing, parsing differ enough to warrant isolation).
- Failure of the user's provider surfaces an error with a one-click **"Retry with Vela default"** action in the UI (no silent fallback).
- Model selection: dropdown filled from the provider's live model listing where the provider has a listing API (OpenAI-compatible `GET /v1/models`, Gemini `GET /v1beta/models`); free text for Anthropic (no listing API exists).
- Keys stored Fernet-encrypted in the Vela DB (same pattern as `UserOAuthIdentity`), one row per user.
- Vertex stays **server-side only** — users cannot configure Vertex.

## Architecture

### Backend

#### `app/core/llm/` provider registry

- `LlmProviderConfig` dataclass: `provider: LlmProviderType`, `base_url: str | None`, `model: str`, `api_key: str`, `extra_headers: dict[str, str]` (covers Gemini key-as-query-param vs header, Vertex `x-goog-api-key`).
- `LlmProviderType` enum: `gemini`, `openai_compatible`, `anthropic`.
- `LlmProvider` abstract base, one method: `async generate_json(prompt: str, schema: dict) -> dict`.
- Implementations, each with `build_request(config, prompt, schema)` and `parse_response(body)` separated from the httpx call so both are unit-testable without network:
  - `GeminiProvider` — moves today's `generateContent` logic out of `client.py` (behavior unchanged: `responseMimeType: application/json` + `responseSchema`, temperature 0).
  - `OpenAICompatibleProvider` — `POST {base_url}/chat/completions`, `response_format: {"type": "json_object"}` (broadly supported across compatible servers; the prompt already carries the full schema), `temperature: 0`, parses `choices[0].message.content`.
  - `AnthropicProvider` — `POST https://api.anthropic.com/v1/messages` with `x-api-key` + `anthropic-version` headers; no native JSON mode, so the prompt instructs JSON-only output and `parse_response` strips markdown code fences if present.
- `registry.py`: `get_provider(config: LlmProviderConfig) -> LlmProvider` — `match/case` on the enum (exhaustive).
- `client.py` keeps the public entry `generate_json(prompt, schema, *, db, user_id, force_server_default=False)`; it resolves config, picks the provider from the registry, calls it. Shared `httpx.AsyncClient` (60s timeout) stays.

#### Config resolution — `resolve_llm_config(db, user_id, force_server_default=False)`

First match wins:

1. `force_server_default` → server env config only (Vertex vars > `VELA_GEMINI_API_KEY`).
2. User has a `UserLlmProvider` row → user config (key decrypted via `app/core/security/secrets.py`).
3. Else → server env config (today's logic in `provider.py`).
4. Else → `None` (callers keep existing behavior: 503 / deterministic git-source fallback).

Existing call sites (`analyze_git_source` in `app/core/git/git_source_analysis.py`, `analyze_repo_stack` in `app/core/stacks/repo_analysis.py`) thread `db` + `user_id` through — both AI features get BYO automatically, no per-feature flags.

#### User storage — `UserLlmProvider` table

One row per user (FK `user_id`, unique): `provider` (enum string), `base_url` (nullable — openai_compatible only), `model`, `api_key_encrypted` (`LargeBinary`, Fernet), `created_at`/`updated_at`. Migration via Alembic. Service functions in `app/core/llm/user_config.py`: `get_user_provider` (never returns the key — `has_key: bool` only), `set_user_provider` (upsert; optional key keeps existing), `delete_user_provider`.

#### LLM result cache

`app/core/llm/cache.py` keys gain `provider` + `model`, so the same repo commit analyzed with different providers/models does not share cached results.

### API routes (all on the existing settings router, authed, own-row only)

| Route | Purpose |
|---|---|
| `GET /api/settings/llm-provider` | `{ provider, base_url, model, has_key }` or `null`. Key is never returned. |
| `PUT /api/settings/llm-provider` | Upsert. Body: `provider`, `base_url?` (required-valid for openai_compatible), `model`, `api_key?` (omit to keep existing key; omitting when no key is saved → 400 "API key required"). Validates: provider/model non-empty; `base_url` is an http(s) URL when present. |
| `DELETE /api/settings/llm-provider` | Remove row → back to server default. |
| `POST /api/settings/llm-provider/test` | Body: candidate config **not saved** (`provider`, `base_url?`, `api_key`, `model?`). Returns `{ ok: true, models?: string[] }` — live `GET {base_url}/v1/models` for openai_compatible, live `GET /v1beta/models` for Gemini, 1-token completion (`max_tokens: 1`) for Anthropic. Failures → 400 with a short mapped message. |

Existing routes touched:

- `POST /api/builder/analyze-source` and `POST /api/stacks/analyze-repo` gain optional `use_server_default: bool` (default `false`) in the request body.
- `GET /api/settings/gemini-status` response extended in place (path kept; frontend is the only consumer): adds `user_provider: { provider, model } | null` so the settings card can distinguish "your provider" / "server default" / "not configured".

### Data flow (git source analysis; stack analysis is identical)

```
POST /api/builder/analyze-source {url, ..., use_server_default?}
  → analyze_git_source(db, user, ...)
    → resolve_llm_config(db, user.id, force_server_default)
        user row? → decrypt → LlmProviderConfig
        else/forced → env (Vertex > Gemini)
        none → existing 503 / deterministic fallback
    → registry.get_provider(config)
    → provider.generate_json(prompt, schema)
        OK   → parse → cache store → 200
        FAIL → LlmProviderError(fallback_available=<server config exists>)
               → 502 { detail, fallback_available: true }
  → UI banner: "Your LLM provider failed. [Retry with Vela default]"
    → re-POST same endpoint with use_server_default: true
```

Unchanged: E2E fixture short-circuits in both service functions, deterministic no-LLM fallback, `LlmNotConfiguredError` → 503 mapping.

### Frontend

#### `LlmProviderCard` (new, `frontend/src/pages/settings/LlmProviderCard.tsx`)

Rendered in `SettingsPage.tsx` above the existing "AI deploy analysis" card. Matches the `ProfileSection.tsx` component pattern:

- Provider select: `OpenAI-compatible` / `Gemini` / `Anthropic`.
- Base URL — openai_compatible only, default `https://api.openai.com/v1`.
- API key — password input; when a key is already saved the field is optional with a "saved" indicator (blank keeps it).
- Model — openai_compatible / Gemini: dropdown populated by a **Load models** button (calls the test endpoint); Anthropic: free text, pre-filled default `claude-sonnet-4-5`.
- Buttons: **Test** (inline success/mapped-failure message), **Save**, **Remove** (destructive → confirm, per repo UX rules).
- Loading skeletons mirroring the final layout; errors near the field with `role="alert"`.

#### `AiPrefillSettingsCard` copy update

Uses the extended `gemini-status`: "Using your own provider (model)" / "Server default (Gemini)" / "Not configured — add your own key in the card above."

#### Retry surface

`useGitSourceAnalysis.ts`, `NewStackModal.tsx`, `ServiceEditForm.tsx`: when the analyze error carries `fallback_available: true`, show the existing `*-banner--err` with a **Retry with Vela default** button that re-calls the same analyze function with `use_server_default: true`. One shared error-shape helper in `frontend/src/api/` so the three call sites don't each parse the error.

New wrappers in `frontend/src/api/settings.ts`: `getLlmProvider`, `putLlmProvider`, `deleteLlmProvider`, `testLlmProvider`.

## Error handling (client-facing messages)

| Failure | Response | UI |
|---|---|---|
| User provider call fails (bad key, rate limit, network, bad JSON) | 502 `{ detail, fallback_available }` | Error banner + **Retry with Vela default** (only when `fallback_available`) |
| User provider fails, no server default configured | 502 `{ detail, fallback_available: false }` | Error banner, no retry button, "or configure a provider in Settings" hint |
| Nothing configured anywhere (no user provider, no server env) | 503 (existing) | Existing "not configured" copy |
| Test endpoint: invalid key / endpoint unreachable / bad URL | 400 with mapped message | Inline under the key/base-url field |
| PUT validation failure (missing model, bad base_url) | 422 (existing schema validation) | Inline field errors |

Details (endpoint, status code) are logged server-side; the `detail` shown to users is short and actionable.

## Testing

- **Backend pytest** (`cd backend && python -m pytest tests -q`):
  - Unit: registry `match` exhaustiveness; `build_request`/`parse_response` per provider (Gemini moves existing logic; OpenAI-compatible payload + content extraction; Anthropic headers + fence-stripping parse); resolution precedence (user > env, `force_server_default` bypasses user, nothing → `None`); Fernet round-trip on `UserLlmProvider`.
  - Integration (TestClient + SQLite): settings CRUD (auth, own-row-only, key never in GET body, keep-existing-key path, validation errors); `/test` endpoint with provider httpx calls monkeypatched (model list 200, 401 → mapped 400, timeout → mapped 400); analyze endpoints with a `UserLlmProvider` row + stubbed `generate_json` (user config reaches the registry) and the failure path — user provider raises → 502 `fallback_available: true` → retry with `use_server_default: true` succeeds on env config; cache key includes provider+model (same commit, different model → no cache hit).
- **Playwright E2E** (`cd frontend && npm run test:e2e`):
  - Settings page: save a fake provider config → card shows configured → remove it. The `/test` provider call is intercepted with `page.route` (permitted for external systems); app-flow mocking stays off.
  - Existing analyze E2E fixture short-circuits untouched.
- **Live eval**: existing `VELA_LLM_EVAL=1` opt-in tier unchanged (exercises server default).
- Both suites must pass before the work is considered complete (AGENTS.md verification rule).

## Out of scope

- Vertex AI as a user provider (server-side only).
- Multiple saved providers per user / per-feature provider selection (one active provider per user).
- Streaming responses, retries/backoff, per-provider rate-limit handling.
- Token/cost accounting or usage meters.
- Anthropic model listing (no API exists).
- Changing prompt versions or analysis schemas for any provider.
