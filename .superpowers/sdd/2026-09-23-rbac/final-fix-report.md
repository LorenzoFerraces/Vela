# RBAC Final Fix Report

## Finding 1: Clerk exchange provisioning and deactivation bypass

- Changed `backend/app/api/routes/auth.py:95-97` so exchange rejects unknown emails with `RegistrationDisabledError` and rejects matched inactive users with `AccountDeactivatedError`, both before identity upsert or token creation.
- Removed the previous Clerk user creation and personal-workspace provisioning path from the route.
- Added/updated tests in `backend/tests/test_clerk_exchange.py:45-110` for unknown Clerk email (403, no user, no identity) and deactivated Clerk-linked user (403, no token, no identity). Updated the existing linked-account test fixture so it provisions both users required by the 409 contract.
- RED evidence: `5 failed, 23 passed, 2 warnings in 41.36s`; the five expected failures were the two Clerk cases, both WebSocket cases, and bootstrap validation.
- GREEN evidence: `28 passed, 2 warnings in 36.09s`.

## Finding 2: WebSocket active-user guard

- Added `backend/app/api/routes/containers.py:160-167`, a small shared token-to-user resolver that rejects missing users and inactive users with the existing WebSocket `NotAuthenticatedError` convention.
- Updated log streaming at `backend/app/api/routes/containers.py:1374` and terminal exec at `backend/app/api/routes/containers.py:1418` to use it.
- Added regression tests in `backend/tests/test_exec_websocket.py:84-110` for both handshake endpoints using a previously issued token after deactivation; both require close code 1008.
- RED evidence: `5 failed, 23 passed, 2 warnings in 41.36s`; the two new WebSocket tests failed because inactive users still received container data/prompt.
- GREEN evidence: `28 passed, 2 warnings in 36.09s`.

## Finding 3: Global audit filter bounds

- Bounded `action` to 200 characters and `target_type` to 80 characters in `backend/app/api/routes/admin.py:64-65`.
- No new test was added for validation; existing audit coverage passed: `24 passed, 1 warning in 11.75s`.

## Finding 4: Bootstrap admin password length

- Added the same 8–128 character policy used by admin-created users in `backend/app/core/auth/bootstrap.py:27`; invalid new bootstrap credentials fail before user creation with a clear `ValueError`.
- Added `backend/tests/test_auth_bootstrap.py:41-56` for a too-short password.
- RED evidence: the focused run failed this case as part of `5 failed, 23 passed, 2 warnings in 41.36s`.
- GREEN evidence: `28 passed, 2 warnings in 36.09s`.

## Verification commands

Environment for pytest commands:

```powershell
$env:VELA_FAKE_ORCHESTRATOR = "1"
$env:VELA_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
```

| Command | Exit status | Result |
|---|---:|---|
| `git status --short; git log --oneline -5` | 0 | Branch state inspected; no test count |
| `..\\.venv\\Scripts\\python.exe -m pytest tests/test_clerk_exchange.py tests/test_exec_websocket.py tests/test_auth_bootstrap.py -q` (RED) | 1 | `5 failed, 23 passed, 2 warnings in 41.36s` |
| `..\\.venv\\Scripts\\python.exe -m pytest tests/test_clerk_exchange.py tests/test_exec_websocket.py tests/test_auth_bootstrap.py -q` (first GREEN attempt) | 1 | `1 failed, 27 passed, 2 warnings in 36.09s`; existing linked-account test needed the second user fixture |
| `..\\.venv\\Scripts\\python.exe -m pytest tests/test_clerk_exchange.py tests/test_exec_websocket.py tests/test_auth_bootstrap.py -q` (final focused) | 0 | `28 passed, 2 warnings in 36.09s` |
| `..\\.venv\\Scripts\\python.exe -m pytest tests -q` (120-second attempt) | timeout | Command exceeded the 120-second tool timeout; no test result |
| `..\\.venv\\Scripts\\python.exe -m pytest tests -q` (300-second attempt) | 0 | `644 passed, 7 skipped, 23 warnings in 161.40s` |
| `..\\.venv\\Scripts\\python.exe -m ruff check .` | 0 | `All checks passed!` |
| `..\\.venv\\Scripts\\python.exe -m pytest tests/test_audit_api.py tests/test_audit_service.py tests/test_audit_user_actions.py tests/test_audit_container_actions.py -q` | 0 | `24 passed, 1 warning in 11.75s` |
| `..\\.venv\\Scripts\\python.exe -m mypy app/ tests/` | 1 | `Found 19 errors in 8 files (checked 204 source files)`; errors are outside this fix wave |
| `git diff --check; git status --short; rg -n ...` | 0 | No diff whitespace errors; line references confirmed |

## Files changed

- `backend/app/api/routes/admin.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/containers.py`
- `backend/app/core/auth/bootstrap.py`
- `backend/tests/test_auth_bootstrap.py`
- `backend/tests/test_clerk_exchange.py`
- `backend/tests/test_exec_websocket.py`

## Concerns / follow-up

- All four findings were fixed as specified. No frontend files were touched.
- Full pytest is green; it reports existing deprecation warnings and aiosqlite event-loop thread warnings in `test_metrics_api.py`.
- `mypy` remains red with 19 pre-existing errors in unrelated files; none is in the changed files.
- Per scope, the login path's 403 behavior for deactivated emails was not changed; retain as a follow-up concern from the review.
- No hard-delete behavior was changed.
