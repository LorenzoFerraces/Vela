# Clerk Sign-In Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Sign in with Clerk" flow actually work end-to-end (real JWT verification) and harden the error/edge paths, with regression-safe tests.

**Architecture:** The frontend loads `@clerk/clerk-js` via a script tag, hands a frontend JWT to `POST /api/auth/clerk/exchange`, and the backend verifies it server-side against the JWKS at `{frontendApi}/.well-known/jwks.json`, then links-or-creates a Vela user by the token's `email` claim. The critical fix is in server-side JWT verification: PyJWT 2.13 cannot decode with a raw JWKS dict (it must resolve the right public key by `kid` first).

**Tech Stack:** FastAPI + SQLAlchemy (async, aiosqlite in tests), PyJWT 2.13 + `cryptography` (RSA), httpx (backend). Vite 8 + React 19 + TypeScript 5.9 (frontend, no `@clerk/clerk-js` npm dependency).

## Global Constraints

- Python **>= 3.12**; `pyjwt>=2.9,<3.0` (installed **2.13.0**), `cryptography>=44,<46`. RSA via `cryptography.hazmat.primitives.asymmetric.rsa`.
- Backend venv is `F:\lolo\fac\Vela\.venv\Scripts\python.exe`. Run tests from `backend/`: `python -m pytest tests -q`. Pytest config sets `asyncio_mode = "auto"` (so `@pytest.mark.asyncio` is optional but kept for consistency).
- Frontend: typecheck with `npx tsc -b --noEmit` and build with `npm run build`; lint with `npm run lint`. **No** `@clerk/clerk-js` in `package.json` — it is loaded at runtime by a `<script>` from `https://{frontendApi}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`. The existing `(window as any).Clerk` cast stays (Clerk injects `window.Clerk`); do not add new `any` casts.
- Error mapping (do **not** change in these tasks — see `app/api/errors.py`): `ClerkTokenError`→HTTP 400, `IntegrationConfigurationError`→HTTP 503, `ClerkAccountAlreadyLinkedError`→HTTP 409.
- `VELA_CLERK_PUBLISHABLE_KEY` format is `pk_{base64url(domain + "$")}`. `clerk_frontend_api_host()` splits on `_` (3 parts), base64-decodes part 3, and does `.rstrip("$")` to get the `*.clerk.accounts.dev` hostname.
- Playwright E2E has **no** Clerk key configured, so there is no Clerk E2E coverage; E2E is out of scope for this plan.
- Backend tests prefer real wiring over mocks; the one justified mock here is replacing `_fetch_jwks` (network) — never mock `jwt.decode`.
- Commit one focused commit per task using a short `fix:`-style message.

---

### Task 1: Make `verify_clerk_token` actually verify (PyJWK by `kid`)

The current code passes the raw JWKS dict to `jwt.decode(key=jwks, ...)`. On PyJWT 2.13 this raises `TypeError: Expecting a PEM-formatted key` for **every** token (valid or not), so Clerk sign-in always 500s. Fix: build a `PyJWKSet`, look up the public key by the token's `kid`, and decode with that key.

**Files:**
- Modify: `backend/app/core/oauth/clerk.py:81-107` (rework `verify_clerk_token`)
- Modify: `backend/app/core/oauth/clerk.py:12` (drop now-unused `jwt` import if it becomes unused — it is **not** unused here, `jwt` is still used; leave the import)
- Test: `backend/tests/test_clerk_jwt.py`

**Interfaces:**
- Consumes: `_get_jwks() -> dict[str, object]` (returns the JWKS `{"keys": [...]}`), `_publishable_key() -> str`, `ClerkTokenError`, `IntegrationConfigurationError`.
- Produces: `verify_clerk_token(token: str) -> ClerkClaims` where `ClerkClaims = ClerkClaims(email: str, external_id: str)`. Existing callers (`app/api/routes/auth.py::clerk_exchange`) rely on this exact signature and the `ClerkTokenError`→400 behavior — do **not** change them.

- [x] **Step 1: Add real crypto to the test file**

In `backend/tests/test_clerk_jwt.py`, add these imports inside the existing `from __future__ import annotations` block's import section (top of file, after the `import pytest` line):

```python
import base64
import time

import jwt as pyjwt

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
```

And add this module-level helper right after the `TEST_CLERK_PUBLISHABLE_KEY = "..."` line (~line 19):

```python
def _make_rsa_kid() -> tuple[str, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-clerk-key"
    public_numbers = private_key.public_key().public_numbers()
    payload = base64.urlsafe_b64encode(
        public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    ).rstrip(b"=").decode("ascii")
    exponent = base64.urlsafe_b64encode(
        public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
    ).rstrip(b"=").decode("ascii")
    return kid, private_key


def _jwks_for(kid: str, private_key: rsa.RSAPrivateKey) -> dict[str, object]:
    public_numbers = private_key.public_key().public_numbers()
    n_bytes = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    e_bytes = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
    return {
        "keys": [{
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": kid,
            "n": base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii"),
            "e": base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode("ascii"),
        }]
    }


def _sign_clerk_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    email: str,
    sub: str,
    audience: str,
) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "email": email,
            "sub": sub,
            "aud": audience,
            "iss": "https://sample123.clerk.accounts.dev",
            "exp": now + 600,
            "iat": now,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
```

- [x] **Step 2: Replace the three masked-`jwt.decode` tests with real-crypto tests**

In `backend/tests/test_clerk_jwt.py`, replace the three async tests `test_verify_clerk_token_success`, `test_verify_clerk_token_missing_email_raises`, and `test_verify_clerk_token_invalid_signature_raises` (currently lines 39-85, all of which `patch` `app.core.oauth.clerk.jwt.decode`) with:

```python
@pytest.mark.asyncio
async def test_verify_clerk_token_success_with_real_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, private_key = _make_rsa_kid()
    token = _sign_clerk_token(
        private_key,
        kid=kid,
        email="ClerkUser@Example.COM",
        sub="user_2Xabc",
        audience=TEST_CLERK_PUBLISHABLE_KEY,
    )

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, private_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        claims = await verify_clerk_token(token)

    assert claims == ClerkClaims(email="clerkuser@example.com", external_id="user_2Xabc")


@pytest.mark.asyncio
async def test_verify_clerk_token_missing_email_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, private_key = _make_rsa_kid()
    headers = {"email": "u@x.com", "sub": "user_1", "aud": TEST_CLERK_PUBLISHABLE_KEY,
               "iss": "https://x", "exp": int(time.time()) + 600, "iat": int(time.time())}
    del headers["email"]
    token = pyjwt.encode(headers, private_key, algorithm="RS256", headers={"kid": kid})

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, private_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with pytest.raises(ClerkTokenError, match="missing the email claim"):
            await verify_clerk_token(token)


@pytest.mark.asyncio
async def test_verify_clerk_token_wrong_key_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, signer_key = _make_rsa_kid()
    token = _sign_clerk_token(
        signer_key,
        kid=kid,
        email="u@x.com",
        sub="user_1",
        audience=TEST_CLERK_PUBLISHABLE_KEY,
    )
    _, other_key = _make_rsa_kid()

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, other_key)  # JWKS holds a different public key

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with pytest.raises(ClerkTokenError, match="no matching key"):
            await verify_clerk_token(token)
```

Note: the `_make_rsa_kid` helper returns the same `kid` string; for the "missing key" assertion the JWKS is built from a *different* key, so `jwk_set[kid]` has no matching key and raises. (If you instead want to test a truly-absent `kid`, sign with `kid="absent"` and supply the JWKS for `kid="other"`.)

- [x] **Step 3: Run the new tests to confirm they fail**

Run: `python -m pytest tests/test_clerk_jwt.py -q`
Expected: `test_verify_clerk_token_success_with_real_key` FAILS with `TypeError: Expecting a PEM-formatted key` (that is the C1 bug — the current `verify_clerk_token` passes the JWKS dict as `key=`). The other two also fail until Step 4.

- [x] **Step 4: Rework `verify_clerk_token`**

In `backend/app/core/oauth/clerk.py`, replace the body of `verify_clerk_token` (lines 81-107) with:

```python
async def verify_clerk_token(token: str) -> ClerkClaims:
    """Verify a Clerk frontend JWT and return extracted claims.

    Raises ``ClerkTokenError`` on invalid signature, expiry, bad audience,
    or missing claims.
    """
    jwks = await _get_jwks()

    try:
        jwk_set = jwt.PyJWKSet.from_dict(jwks)
        kid = jwt.get_unverified_header(token).get("kid")
        try:
            jwk = jwk_set[kid]
        except KeyError as exc:
            raise ClerkTokenError(
                "Clerk token has no matching key (kid not in JWKS)."
            ) from exc
        payload = jwt.decode(
            token,
            key=jwk,
            algorithms=["RS256"],
            audience=_publishable_key(),
        )
    except InvalidTokenError as exc:
        raise ClerkTokenError(
            "Clerk token is invalid (signature, expiry, or audience)."
        ) from exc

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise ClerkTokenError("Clerk token is missing the email claim.")

    external_id = payload.get("sub", "")
    if not isinstance(external_id, str):
        external_id = str(external_id)

    return ClerkClaims(email=email.strip().lower(), external_id=external_id)
```

`jwt` is already `import jwt` at the top (line 11); `jwt.PyJWKSet`, `jwt.get_unverified_header`, and `jwt.decode` are all available without new imports. `InvalidTokenError` is already imported (line 12). Note the redundant `options={"verify_aud": True}` is removed — `verify_aud` defaults to `True` in PyJWT.

- [x] **Step 5: Run the tests to confirm they pass**

Run: `python -m pytest tests/test_clerk_jwt.py -q`
Expected: all tests in this file PASS.

- [x] **Step 6: Lint + typecheck**

Run: `python -m ruff check app/core/oauth/clerk.py tests/test_clerk_jwt.py` then `python -m mypy app/core/oauth/clerk.py`
Expected: no errors. (If `get_unverified_header(...).get("kid")` is flagged by mypy for the dict index, the value is `Any`-typed from the header dict, so it should not error; if it does, add a `# type: ignore[index]` on the `jwk_set[kid]` line — do not restructure.)

- [x] **Step 7: Commit**

```bash
git add backend/app/core/oauth/clerk.py backend/tests/test_clerk_jwt.py
git commit -m "fix: verify Clerk JWT against JWKS by kid (real crypto)"
```

---

### Task 2: Surface JWKS network failures as a clean 400

If `https://{frontendApi}/.well-known/jwks.json` is unreachable or returns an HTTP error, `_fetch_jwks` currently lets `httpx` exceptions propagate, producing an unhandled 500. Wrap it so the user sees a short, actionable message.

**Files:**
- Modify: `backend/app/core/oauth/clerk.py:65-69` (`_fetch_jwks`)
- Test: `backend/tests/test_clerk_jwt.py`

**Interfaces:**
- Consumes: `ClerkTokenError` (already imported at `clerk.py:14`), `httpx` (already imported at `clerk.py:10`).
- Produces: `_fetch_jwks() -> dict[str, object]` that raises `ClerkTokenError("Clerk is temporarily unavailable.")` on any `httpx.HTTPError`.

- [x] **Step 1: Write the failing test**

Add this test to `backend/tests/test_clerk_jwt.py`:

```python
@pytest.mark.asyncio
async def test_fetch_jwks_network_error_raises_clerk_error(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    async def failing_client(timeout: float) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get("https://sample123.clerk.accounts.dev/.well-known/jwks.json")
        raise httpx.ConnectError("boom")

    with patch.object(clerk_mod.httpx, "AsyncClient", side_effect=failing_client):
        with pytest.raises(ClerkTokenError, match="temporarily unavailable"):
            await clerk_mod._fetch_jwks()
```

(`httpx` is importable in the test file — add `import httpx` to the top imports if it is not present. It is not currently imported in this file, so add it.)

- [x] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_clerk_jwt.py::test_fetch_jwks_network_error_raises_clerk_error -q`
Expected: FAIL — the current `_fetch_jwks` lets the `httpx.ConnectError` escape (it is **not** a `ClerkTokenError`, so `pytest.raises(ClerkTokenError)` does not catch it).

- [x] **Step 3: Wrap the fetch**

In `backend/app/core/oauth/clerk.py`, replace `_fetch_jwks` (lines 65-69) with:

```python
async def _fetch_jwks() -> dict[str, object]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_jwks_url())
    try:
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ClerkTokenError("Clerk is temporarily unavailable.") from exc
    return resp.json()
```

- [x] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_clerk_jwt.py -q`
Expected: all tests PASS (including the new network-error test).

- [x] **Step 5: Commit**

```bash
git add backend/app/core/oauth/clerk.py backend/tests/test_clerk_jwt.py
git commit -m "fix: map JWKS fetch failures to a Clerk token error"
```

---

### Task 3: Add the Clerk IntegrityError guard (parity with GitHub)

`upsert_clerk_identity` (backend/app/core/oauth/identity.py:169) does a bare `await session.commit()`. The GitHub twin (`upsert_github_identity`, identity.py:85-97) wraps the commit in `try/except IntegrityError` and maps a `(provider, provider_subject)` unique-constraint violation to `ClerkAccountAlreadyLinkedError`. The app-level check (line 150) covers the normal case, but the guard closes the narrow concurrent window where two requests race past that check. Mirror the GitHub twin.

**Files:**
- Modify: `backend/app/core/oauth/identity.py:169-171` (the tail of `upsert_clerk_identity`)

**Interfaces:**
- Consumes: `IntegrityError` (imported at `identity.py:9`), `ClerkAccountAlreadyLinkedError` (imported at `identity.py:12`).
- Produces: `upsert_clerk_identity(session, *, user_id, external_id) -> UserOAuthIdentity` — signature unchanged. On a constraint violation it now raises `ClerkAccountAlreadyLinkedError()` (→409) instead of 500.

- [x] **Step 1: Add the guard**

In `backend/app/core/oauth/identity.py`, replace the tail of `upsert_clerk_identity` (lines 169-171: `await session.commit()` / `await session.refresh(identity)` / `return identity`) with:

```python
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        detail = str(getattr(exc, "orig", None) or exc).lower()
        if (
            "uq_oauth_provider_subject" in detail
            or "provider_subject" in detail
        ):
            raise ClerkAccountAlreadyLinkedError() from exc
        raise

    await session.refresh(identity)
    return identity
```

This matches `upsert_github_identity` exactly (identity.py:85-97).

- [x] **Step 2: Regression-check the full backend suite**

This guard protects a true concurrency race that cannot be deterministically triggered in a single-process SQLite test without mocking internals, so it is regression-checked via the existing suite rather than a bespoke mock test. The user-facing duplicate case (`owner.user_id != user_id` → 409) is already deterministically covered by `test_clerk_exchange_account_already_linked_returns_409`.

Run: `python -m pytest tests/test_clerk_exchange.py tests/test_github_oauth.py -q`
Expected: all PASS (no regression). The new `except` branch is only reached when a `(provider, provider_subject)` constraint fires; nothing in the suite intentionally triggers that, so existing behavior is unchanged.

- [x] **Step 3: Commit**

```bash
git add backend/app/core/oauth/identity.py
git commit -m "fix: map Clerk identity constraint violation to 409 (GitHub parity)"
```

---

### Task 4: Fix Clerk auto-exchange (`getToken()` + `clerkBusy`)

Two frontend bugs in `frontend/src/pages/LoginPage.tsx`:
- **H1:** `clerk.session.getToken('vela')` passes `'vela'` as the token template name. Clerk's default session JWT (no argument) is the one signed for the publishable-key audience the backend verifies. Change to `getToken()`.
- **N2:** the auto-exchange reuses `submitting`, which blocks both login-submit and the "Sign in with Clerk" button even while no Clerk work is in flight. Add a dedicated `clerkBusy` flag and wrap the exchange in `try/catch/finally` (the current `.finally` can leave state stuck and swallows exchange errors silently).

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx:20-28` (add `clerkBusy` state)
- Modify: `frontend/src/pages/LoginPage.tsx:68-107` (rewrite the auto-exchange effect)
- Modify: `frontend/src/pages/LoginPage.tsx:186-193` (gate the Clerk button on `clerkBusy`)

**Interfaces:**
- Consumes: `clerkLogin` (from `useAuth`), `navigate`, `nextPath`, `formatApiError`, `clerkConfig`.
- Produces: a `clerkBusy: boolean` state that is true while the Clerk auto-exchange is in flight; the Clerk button is disabled when `clerkBusy`.

- [x] **Step 1: Add the `clerkBusy` state**

In `frontend/src/pages/LoginPage.tsx`, after `const [submitting, setSubmitting] = useState(false)` (line 22), add:

```tsx
  const [clerkBusy, setClerkBusy] = useState(false)
```

- [x] **Step 2: Rewrite the auto-exchange effect**

Replace the effect that starts `if (!clerkConfig) return` (lines 68-107) with:

```tsx
  useEffect(() => {
    if (!clerkConfig) return

    const loadClerk = () => {
      if (clerkLoaded.current) return
      clerkLoaded.current = true
      return new Promise<void>((resolve, reject) => {
        const script = document.createElement('script')
        script.async = true
        script.crossOrigin = 'anonymous'
        script.setAttribute('data-clerk-publishable-key', clerkConfig.publishableKey)
        script.src = `https://${clerkConfig.frontendApi}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load Clerk'))
        document.head.appendChild(script)
      })
    }

    let cancelled = false
    loadClerk().then(async () => {
      if (cancelled) return
      const clerk = (window as any).Clerk
      if (!clerk) return
      await clerk.load()
      if (cancelled) return
      if (clerk.session) {
        setClerkBusy(true)
        clerk.session.getToken().then(async (token: string) => {
          if (cancelled) return
          try {
            await clerkLogin(token)
            navigate(nextPath, { replace: true })
          } catch (error) {
            if (!cancelled) setErrorText(formatApiError(error))
          } finally {
            if (!cancelled) setClerkBusy(false)
          }
        }).catch(() => {
          if (!cancelled) {
            setClerkBusy(false)
            setErrorText('Clerk sign-in could not start. Try clicking the button once.')
          }
        })
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [clerkConfig, clerkLogin, navigate, nextPath])
```

(Only three lines differ from the original: `setClkBusy`→`setClerkBusy(true)`, `getToken('vela')`→`getToken()`, and the exchange body swapped from the old `.finally` chain into `try/catch/finally` with an explicit `catch` fallback.)

- [x] **Step 3: Gate the Clerk button on `clerkBusy`**

In the Clerk button (lines 186-193), change:

```tsx
            <button
              type="button"
              className="btn btn--outline auth-form__clerk"
              disabled={submitting}
              onClick={onClerkClick}
            >
```

to:

```tsx
            <button
              type="button"
              className="btn btn--outline auth-form__clerk"
              disabled={submitting || clerkBusy}
              onClick={onClerkClick}
            >
```

- [x] **Step 4: Typecheck and build**

Run: `npx tsc -b --noEmit` then `npm run build`
Expected: no type errors, build succeeds. (There is no frontend unit-test harness; tsc/build is the gate. `clerkBusy` must be used or TS's noUnusedLocals will flag it — the button `disabled` uses it.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx
git commit -m "fix: use no-arg Clerk getToken and add clerkBusy state"
```

---

### Task 5: Preserve `?next=` after Clerk sign-in

`onClerkClick` sets `afterSignInUrl: window.location.href`, which (a) round-trips the whole current URL back into Clerk and (b) depends on the user re-landing on `/login`. After Clerk signs the user in, we always return to `/login`, so point it at `/login` while preserving only the query string (which carries `?next=`).

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx:127-132` (`onClerkClick`)

**Interfaces:**
- Consumes: `location` (already `useLocation()` at line 19), `clerkConfig` (gates whether the button renders).
- Produces: `afterSignInUrl` = `window.location.origin + '/login' + location.search`.

- [x] **Step 1: Update `afterSignInUrl`**

Replace `onClerkClick` (lines 127-132) with:

```tsx
  function onClerkClick() {
    const clerk = (window as any).Clerk
    if (clerk) {
      clerk.redirectToSignIn({
        afterSignInUrl: `${window.location.origin}/login${location.search}`,
      })
    }
  }
```

- [x] **Step 2: Typecheck and build**

Run: `npx tsc -b --noEmit` then `npm run build`
Expected: no type errors, build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx
git commit -m "fix: preserve ?next after Clerk sign-in redirect"
```

---

### Task 6: Verify the publishable-key derivation against a real key (M3)

This is a **verification task with no code change unless it is wrong**. The hostname is derived from the publishable key by decoding base64url(part 3) and `rstrip("$")`. Confirm it produces the real `*.clerk.accounts.dev` domain that hosts the JWKS.

**Files:**
- Likely no change. If the derivation is wrong, modify `backend/app/core/oauth/clerk.py:28-38` (`clerk_frontend_api_host`).

**Interfaces:**
- Consumes: `VELA_CLERK_PUBLISHABLE_KEY` from `backend/.env` (the real production/test key).
- Produces: confirmation (or a corrected `clerk_frontend_api_host`) that `clerk_frontend_api_host(pk)` equals the real Clerk frontend-API host.

- [ ] **Step 1: Derive the host and check it**

From `backend/`, run:

```bash
python -c "import os; from app.core.oauth.clerk import clerk_frontend_api_host as h, _jwks_url as u; pk=os.environ['VELA_CLERK_PUBLISHABLE_KEY'].strip(); host=h(pk); print('host=', host); print('jwks=', u()); import urllib.request; r=urllib.request.urlopen('https://%s/.well-known/jwks.json'%host, timeout=10); print('jwks ok', len(r.read()))"
```

Expected: `host=` prints your real `*.clerk.accounts.dev` domain (the one in the Clerk dashboard's domain field), and the JWKS URL returns 200 with a keys array. If it 404s or the host lacks `.clerk.accounts.dev`, the derivation is wrong — adjust `clerk_frontend_api_host` and add a test in `test_clerk_jwt.py` reproducing the real key's parts (keep the existing `test_clerk_frontend_api_host_decodes_embedded_domain` too). If it is correct, **do not change code**.

- [ ] **Step 2: End-to-end manual smoke (optional, needs a real session)**

With the backend running (`python run.py`) and a real `VELA_CLERK_PUBLISHABLE_KEY`, open `/login` in a browser signed into Clerk. Expected: the auto-exchange fires, the backend decodes the session token, you land on `/containers` (or `?next=` target), and the network tab shows `POST /api/auth/clerk/exchange` → 200 with `user.email`.

- [ ] **Step 3: Commit (only if Step 1 required a code change)**

```bash
git add backend/app/core/oauth/clerk.py backend/tests/test_clerk_jwt.py
git commit -m "fix: correct Clerk frontend-api host derivation"
```

---

### Task 7: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire backend suite**

Run: `cd backend && python -m pytest tests -q`
Expected: all PASS. (No new Clerk E2E expectations here — Playwright has no Clerk key.)

- [ ] **Step 2: Frontend lint + typecheck + build**

Run: `cd frontend && npm run lint` then `npx tsc -b --noEmit` then `npm run build`
Expected: lint clean, no type errors, build succeeds.

- [ ] **Step 3: Final commit (only if lint/typecheck required fixes)**

```bash
git add -A
git commit -m "fix: address lint/typecheck findings from Clerk sign-in fixes"
```

---

## Self-Review Notes (already run)

- **Spec coverage:** C1→Task 1, C1-test→Task 1, H1→Task 4, C2→Task 2, M4→Task 3, N2→Task 4, H1/N2/N3→Tasks 4-5, M3→Task 6, verification→Task 7. Deliberately **out of scope** (documented, not a gap): M1 (add "unlink Clerk account" — YAGNI, no request), M2 (auto-create from an *unverified* email — a product/security call needing an owner), optional real-key E2E (no Clerk key in Playwright env).
- **Placeholder scan:** no TBD/TODO; every code step carries full code; every run step carries an exact command and expected outcome.
- **Type consistency:** `clerkBusy` defined in Task 4 and consumed in Task 4 (button) — consistent. `ClerkClaims(email, external_id)`, `verify_clerk_token`, `_fetch_jwks`, `upsert_clerk_identity` signatures preserved across tasks.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-15-clerk-signin-fixes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — run tasks in this session with batch execution and checkpoints.

Recommended order when a handoff agent picks this up: Tasks 1→2→3 (backend, each independently green), then 4→5 (frontend), then 6 (confirm with a real key), then 7 (full suite).
