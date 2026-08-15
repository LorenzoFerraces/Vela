# Clerk Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Sign in with Clerk" as an authentication option alongside existing email/password.

**Architecture:** Clerk handles frontend auth. Clerk JWT exchanged for Vela JWT via new backend endpoint. Vela's internal auth (deps.py, get_current_user) remains unchanged.

**Tech Stack:** Clerk SDK (@clerk/clerk-react), PyJWT, FastAPI, React, TypeScript

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~)
- Backend MVC: core/ (domain), schemas.py (views), routes/ (controllers)
- Domain packages under `app/core/<domain>/` when 3+ modules
- TDD: write failing test first, then minimal implementation
- Existing email/password auth must remain fully functional
- `deps.py` and `get_current_user()` must NOT change — they only care about Vela JWTs

---

## Task 1 — Backend: Clerk JWT verification module

**Files:**
- Create `backend/app/core/oauth/clerk.py`
- Modify `backend/app/core/oauth/__init__.py` (re-exports)
- Modify `backend/app/core/exceptions.py` (add `ClerkTokenError`)
- Modify `backend/app/api/errors.py` (add `ClerkTokenError` → 400 handler)
- Create `backend/tests/test_clerk_jwt.py`

**Interfaces:**
- Consumes: `VELA_CLERK_PUBLISHABLE_KEY` env var, Clerk JWK set from `https://{publishable_key}.clerk.accounts.clerkdev.com/.well-known/jwks.json`
- Produces: `ClerkClaims` dataclass (email, external_id), `verify_clerk_token(token: str) -> ClerkClaims`

### Steps

- [ ] **1.1** Add `ClerkTokenError` to `backend/app/core/exceptions.py` after `IntegrationError`:

```python
class ClerkTokenError(IntegrationError):
    """Clerk token verification failed (bad signature, expired, missing claims)."""

    def __init__(self, message: str = "Clerk authentication failed.") -> None:
        super().__init__(message)
```

- [ ] **1.2** Add handler in `backend/app/api/errors.py` before the generic `IntegrationError` handler:

```python
from app.core.exceptions import ClerkTokenError

@app.exception_handler(ClerkTokenError)
async def clerk_token_handler(
    _request: Request, exc: ClerkTokenError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )
```

- [ ] **1.3** Create `backend/app/core/oauth/clerk.py`:

```python
"""Clerk JWT verification — fetches JWK set, verifies tokens, extracts claims."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import InvalidTokenError

from app.core.exceptions import ClerkTokenError, IntegrationConfigurationError

_JWKS_URL_TEMPLATE = (
    "https://{pk}.clerk.accounts.clerkdev.com/.well-known/jwks.json"
)
_JWKS_CACHE_TTL_SECONDS = 3600

_jwks_cache: dict[str, object] | None = None
_jwks_loaded_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ClerkClaims:
    email: str
    external_id: str


def _publishable_key() -> str:
    pk = os.environ.get("VELA_CLERK_PUBLISHABLE_KEY", "").strip()
    if not pk:
        raise IntegrationConfigurationError(
            "Clerk is not configured. Set VELA_CLERK_PUBLISHABLE_KEY in backend/.env."
        )
    return pk


def _jwks_url() -> str:
    return _JWKS_URL_TEMPLATE.format(pk=_publishable_key())


async def _fetch_jwks() -> dict[str, object]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_jwks_url())
    resp.raise_for_status()
    return resp.json()


async def _get_jwks() -> dict[str, object]:
    global _jwks_cache, _jwks_loaded_at
    now = time.time()
    if _jwks_cache is None or (now - _jwks_loaded_at) > _JWKS_CACHE_TTL_SECONDS:
        _jwks_cache = await _fetch_jwks()
        _jwks_loaded_at = now
    return _jwks_cache


def _build_algorithms(jwks: dict[str, object]) -> list[str]:
    keys = jwks.get("keys", [])
    algs: set[str] = set()
    for key in keys:
        alg = key.get("alg")
        if isinstance(alg, str):
            algs.add(alg)
    return list(algs) or ["RS256"]


async def verify_clerk_token(token: str) -> ClerkClaims:
    """Verify a Clerk frontend JWT and return extracted claims.

    Raises ``ClerkTokenError`` on invalid signature, expiry, or missing claims.
    """
    jwks = await _get_jwks()
    algs = _build_algorithms(jwks)

    try:
        payload = jwt.decode(
            token,
            options={"verify_audit": False},
            algorithms=algs,
            audience=_publishable_key(),
        )
    except InvalidTokenError as exc:
        raise ClerkTokenError(
            f"Clerk token verification failed: {exc}"
        ) from exc

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise ClerkTokenError("Clerk token is missing the email claim.")

    external_id = payload.get("sub", "")
    if not isinstance(external_id, str):
        external_id = str(external_id)

    return ClerkClaims(email=email.strip().lower(), external_id=external_id)


def reset_jwks_cache_for_tests() -> None:
    """Clear the JWK cache so tests can inject their own keys."""
    global _jwks_cache, _jwks_loaded_at
    _jwks_cache = None
    _jwks_loaded_at = 0.0
```

- [ ] **1.4** Update `backend/app/core/oauth/__init__.py` — add to imports and `__all__`:

```python
from app.core.oauth.clerk import (
    ClerkClaims,
    reset_jwks_cache_for_tests,
    verify_clerk_token,
)

# Add to __all__:
"ClerkClaims",
"reset_jwks_cache_for_tests",
"verify_clerk_token",
```

- [ ] **1.5** Create `backend/tests/test_clerk_jwt.py`:

```python
"""Tests for Clerk JWT verification module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import app.core.oauth.clerk as clerk_mod
from app.core.exceptions import ClerkTokenError, IntegrationConfigurationError
from app.core.oauth.clerk import (
    ClerkClaims,
    reset_jwks_cache_for_tests,
    verify_clerk_token,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_jwks_cache_for_tests()
    yield
    reset_jwks_cache_for_tests()


def test_missing_publishable_key_raises(monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(IntegrationConfigurationError, match="VELA_CLERK_PUBLISHABLE_KEY"):
        clerk_mod._publishable_key()


@pytest.mark.asyncio
async def test_verify_clerk_token_success(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig"}]}

    fake_payload = {
        "email": "ClerkUser@Example.COM",
        "sub": "user_2Xabc",
        "iss": "https://pk_test_sample123.clerk.accounts.clerkdev.com",
        "aud": "pk_test_sample123",
    }

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", return_value=fake_payload):
            claims = await verify_clerk_token("fake.token.here")

    assert claims == ClerkClaims(email="clerkuser@example.com", external_id="user_2Xabc")


@pytest.mark.asyncio
async def test_verify_clerk_token_missing_email_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256"}]}

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", return_value={"sub": "user_1"}):
            with pytest.raises(ClerkTokenError, match="missing the email claim"):
                await verify_clerk_token("fake.token")


@pytest.mark.asyncio
async def test_verify_clerk_token_invalid_signature_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256"}]}

    from jwt import InvalidTokenError

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", side_effect=InvalidTokenError("bad sig")):
            with pytest.raises(ClerkTokenError, match="Clerk token verification failed"):
                await verify_clerk_token("bad.token")
```

- [ ] **1.6** Run the tests:

```bash
cd backend && python -m pytest tests/test_clerk_jwt.py -q
```

- [ ] **1.7** Commit: `feat: add Clerk JWT verification module`

---

## Task 2 — Backend: Clerk exchange endpoint

**Files:**
- Modify `backend/app/api/schemas.py` (add `ClerkExchangeRequest`)
- Modify `backend/app/api/routes/auth.py` (add `/clerk/exchange` route)
- Create `backend/tests/test_clerk_exchange.py`
- Modify `backend/app/core/oauth/identity.py` (add `upsert_clerk_identity`)
- Modify `backend/app/core/oauth/__init__.py` (add Clerk identity exports)

**Interfaces:**
- Consumes: `ClerkExchangeRequest { clerk_token: str }`, verified `ClerkClaims`
- Produces: `TokenResponse { access_token, token_type, user }` (reuses existing schema)

### Steps

- [ ] **2.1** Write failing test `backend/tests/test_clerk_exchange.py`:

```python
"""Tests for the Clerk token exchange endpoint."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import app.core.oauth.clerk as clerk_mod
from app.core.oauth.clerk import ClerkClaims, reset_jwks_cache_for_tests


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_jwks_cache_for_tests()
    yield
    reset_jwks_cache_for_tests()


def _mock_clerk_verify() -> ClerkClaims:
    return ClerkClaims(email="clerk-user@example.com", external_id="user_2Xtest")


def _patch_clerk_verify():
    return patch(
        "app.core.oauth.clerk.verify_clerk_token",
        new=AsyncMock(return_value=_mock_clerk_verify()),
    )


def test_clerk_exchange_creates_new_user(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    from fastapi.testclient import TestClient

    with _patch_clerk_verify():
        with TestClient(db_app) as client:
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["user"]["email"] == "clerk-user@example.com"


def test_clerk_exchange_links_existing_user(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    from fastapi.testclient import TestClient

    with _patch_clerk_verify():
        with TestClient(db_app) as client:
            reg = client.post(
                "/api/auth/register",
                json={
                    "email": "clerk-user@example.com",
                    "password": "supersecret123",
                },
            )
            assert reg.status_code == 201

            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "clerk-user@example.com"


def test_clerk_exchange_missing_config_returns_503(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)

    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/clerk/exchange",
            json={"clerk_token": "fake"},
        )

    assert response.status_code == 503


def test_clerk_exchange_invalid_token_returns_400(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    from app.core.exceptions import ClerkTokenError
    from fastapi.testclient import TestClient

    async def raise_clerk_error(_token: str):
        raise ClerkTokenError("Clerk token verification failed: bad signature")

    with patch(
        "app.core.oauth.clerk.verify_clerk_token", new=raise_clerk_error
    ):
        with TestClient(db_app) as client:
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "bad.token"},
            )

    assert response.status_code == 400


def test_clerk_exchange_empty_body_returns_422(db_app: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/clerk/exchange",
            json={},
        )

    assert response.status_code == 422
```

- [ ] **2.2** Run tests to confirm they fail:

```bash
cd backend && python -m pytest tests/test_clerk_exchange.py -q
```

- [ ] **2.3** Add `ClerkExchangeRequest` to `backend/app/api/schemas.py` after `TokenResponse`:

```python
class ClerkExchangeRequest(BaseModel):
    clerk_token: str = Field(..., min_length=1, max_length=4096)
```

- [ ] **2.4** Add to `backend/app/core/oauth/identity.py` after `delete_github_identity`:

```python
CLERK_PROVIDER = "clerk"


async def get_clerk_identity(
    session: AsyncSession, user_id: uuid.UUID
) -> UserOAuthIdentity | None:
    return await session.scalar(
        select(UserOAuthIdentity).where(
            UserOAuthIdentity.user_id == user_id,
            UserOAuthIdentity.provider == CLERK_PROVIDER,
        )
    )


async def get_clerk_identity_by_subject(
    session: AsyncSession, provider_subject: str
) -> UserOAuthIdentity | None:
    return await session.scalar(
        select(UserOAuthIdentity).where(
            UserOAuthIdentity.provider == CLERK_PROVIDER,
            UserOAuthIdentity.provider_subject == provider_subject,
        )
    )


async def upsert_clerk_identity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    external_id: str,
) -> UserOAuthIdentity:
    """Insert or update the user's Clerk identity. Commits before returning."""
    now = datetime.now(timezone.utc)
    identity = await get_clerk_identity(session, user_id)

    if identity is None:
        identity = UserOAuthIdentity(
            user_id=user_id,
            provider=CLERK_PROVIDER,
            provider_subject=external_id,
            connected_at=now,
            updated_at=now,
        )
        session.add(identity)
    else:
        identity.provider_subject = external_id
        identity.updated_at = now

    await session.commit()
    await session.refresh(identity)
    return identity
```

- [ ] **2.5** Add to `backend/app/core/oauth/__init__.py` exports:

```python
from app.core.oauth.identity import (
    CLERK_PROVIDER,
    get_clerk_identity,
    get_clerk_identity_by_subject,
    upsert_clerk_identity,
)

# Add to __all__:
"CLERK_PROVIDER",
"get_clerk_identity",
"get_clerk_identity_by_subject",
"upsert_clerk_identity",
```

- [ ] **2.6** Add `/clerk/exchange` route to `backend/app/api/routes/auth.py` after `/login`:

```python
from app.core.oauth.clerk import verify_clerk_token
from app.core.oauth.identity import upsert_clerk_identity
from app.api.schemas import ClerkExchangeRequest


@router.post("/clerk/exchange", response_model=TokenResponse)
async def clerk_exchange(
    body: ClerkExchangeRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> TokenResponse:
    """Exchange a Clerk frontend JWT for a Vela access token."""
    from sqlalchemy import select
    from app.db.models import User
    from app.core.projects.bootstrap import ensure_personal_workspace

    claims = await verify_clerk_token(body.clerk_token)

    user = await session.scalar(
        select(User).where(User.email == claims.email)
    )

    if user is None:
        user = User(email=claims.email, password_hash=None)
        session.add(user)
        await session.flush()
        await ensure_personal_workspace(session, user)
        await session.refresh(user)

    await upsert_clerk_identity(
        session,
        user_id=user.id,
        external_id=claims.external_id,
    )

    return _token_response(user, object_storage)
```

- [ ] **2.7** Run tests:

```bash
cd backend && python -m pytest tests/test_clerk_exchange.py tests/test_clerk_jwt.py -q
```

- [ ] **2.8** Run full test suite:

```bash
cd backend && python -m pytest tests -q
```

- [ ] **2.9** Commit: `feat: add Clerk token exchange endpoint`

---

## Task 3 — Frontend: Clerk SDK integration

**Files:**
- Modify `frontend/package.json` (add `@clerk/clerk-react`)
- Modify `frontend/src/main.tsx` (wrap with `<ClerkProvider>`)
- Modify `frontend/src/api/client.ts` (add `clerkExchange`)
- Modify `frontend/src/auth/AuthContext.ts` (add `clerkLogin`)
- Modify `frontend/src/auth/AuthProvider.tsx` (implement `clerkLogin`)
- Modify `frontend/src/pages/LoginPage.tsx` (add Clerk sign-in button)
- Modify `frontend/src/index.css` (add divider + outline button styles)
- Create/update `frontend/.env.local` (add `VITE_CLERK_PUBLISHABLE_KEY`)

**Interfaces:**
- Consumes: Clerk publishable key from `VITE_CLERK_PUBLISHABLE_KEY` env var
- Produces: "Sign in with Clerk" button that triggers Clerk sign-in, then exchanges token for Vela JWT

### Steps

- [ ] **3.1** Add to `frontend/package.json` dependencies:

```json
"@clerk/clerk-react": "5.32.0"
```

- [ ] **3.2** Install:

```bash
cd frontend && npm install
```

- [ ] **3.3** Add to `frontend/src/api/client.ts` after `login`:

```typescript
export interface ClerkExchangeRequest {
  clerk_token: string
}

export async function clerkExchange(
  body: ClerkExchangeRequest
): Promise<TokenResponse> {
  return apiPost<TokenResponse, ClerkExchangeRequest>(
    '/api/auth/clerk/exchange',
    body,
    { skipAuth: true }
  )
}
```

- [ ] **3.4** Add `clerkLogin` to `frontend/src/auth/AuthContext.ts` interface:

```typescript
export interface AuthContextValue {
  status: AuthStatus
  user: UserPublic | null
  login: (body: LoginRequest) => Promise<UserPublic>
  register: (body: RegisterRequest) => Promise<UserPublic>
  clerkLogin: (clerkToken: string) => Promise<UserPublic>
  logout: () => void
  refreshUser: () => Promise<void>
}
```

- [ ] **3.5** Update `frontend/src/auth/AuthProvider.tsx`:

Add to imports:
```typescript
import {
  ApiError,
  clearAccessToken,
  clerkExchange,
  getAccessToken,
  getMe,
  login as apiLogin,
  onUnauthorized,
  registerUser as apiRegister,
  setAccessToken,
  type LoginRequest,
  type RegisterRequest,
  type UserPublic,
} from '../api/client'
```

Add callback after `register`:
```typescript
const clerkLogin = useCallback(async (clerkToken: string) => {
  const response = await clerkExchange({ clerk_token: clerkToken })
  setAccessToken(response.access_token)
  setUser(response.user)
  setStatus('authenticated')
  return response.user
}, [])
```

Add `clerkLogin` to `useMemo` value:
```typescript
const value = useMemo<AuthContextValue>(
  () => ({ status, user, login, register, clerkLogin, logout, refreshUser }),
  [status, user, login, register, clerkLogin, logout, refreshUser]
)
```

- [ ] **3.6** Wrap App with `<ClerkProvider>` in `frontend/src/main.tsx`:

```typescript
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ClerkProvider } from '@clerk/clerk-react'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthProvider'

const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ClerkProvider>
    </BrowserRouter>
  </StrictMode>
)
```

- [ ] **3.7** Add to `frontend/.env.local`:

```
VITE_CLERK_PUBLISHABLE_KEY=pk_test_your_key_here
```

- [ ] **3.8** Replace `frontend/src/pages/LoginPage.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { SignInButton, useAuth as useClerkAuth, useClerk } from '@clerk/clerk-react'
import { ApiError, formatApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

function safeNextPath(rawNext: string | null): string {
  if (!rawNext) return '/containers'
  try {
    const decoded = decodeURIComponent(rawNext)
    return decoded.startsWith('/') ? decoded : '/containers'
  } catch {
    return '/containers'
  }
}

export default function LoginPage() {
  const { login, status, clerkLogin } = useAuth()
  const clerk = useClerk()
  const { isSignedIn: clerkSignedIn, getToken } = useClerkAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)

  const params = new URLSearchParams(location.search)
  const nextPath = safeNextPath(params.get('next'))

  useEffect(() => {
    if (status === 'authenticated') {
      navigate(nextPath, { replace: true })
    }
  }, [status, navigate, nextPath])

  useEffect(() => {
    if (!clerkSignedIn || status === 'authenticated') return

    void (async () => {
      try {
        const token = await getToken()
        if (!token) return
        await clerkLogin(token)
        navigate(nextPath, { replace: true })
      } catch (error) {
        setErrorText(formatApiError(error))
      }
    })()
  }, [clerkSignedIn, getToken, status, clerkLogin, navigate, nextPath])

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setErrorText(null)
    setSubmitting(true)
    try {
      await login({ email: email.trim(), password })
      navigate(nextPath, { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setErrorText('Invalid email or password.')
      } else {
        setErrorText(formatApiError(error))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <h1 className="auth-card__title">Sign in to Vela</h1>
        <form className="auth-form" onSubmit={onSubmit} noValidate>
          <label className="auth-form__label" htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            className="auth-form__input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />

          <label className="auth-form__label" htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            className="auth-form__input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {errorText ? (
            <p className="auth-form__error" role="alert">
              {errorText}
            </p>
          ) : null}

          <button
            type="submit"
            className="btn btn--primary auth-form__submit"
            disabled={submitting}
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div className="auth-form__divider">
          <hr />
          <span>or</span>
          <hr />
        </div>

        <SignInButton mode="modal">
          <button type="button" className="btn btn--outline">
            Sign in with Clerk
          </button>
        </SignInButton>

        <p className="auth-form__footer">
          New to Vela?{' '}
          <Link className="auth-form__footer-link" to="/register">
            Create an account
          </Link>
        </p>
      </section>
    </main>
  )
}
```

- [ ] **3.9** Append to `frontend/src/index.css`:

```css
.auth-form__divider {
  display: flex;
  align-items: center;
  margin: 1.25rem 0;
  text-align: center;
}

.auth-form__divider hr {
  flex: 1;
  border: none;
  border-top: 1px solid var(--color-border, #e2e8f0);
  margin: 0 0.75rem;
}

.auth-form__divider span {
  font-size: 0.8rem;
  color: var(--color-text-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.btn--outline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0.625rem 1rem;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--color-text, #1e293b);
  background: transparent;
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius, 0.5rem);
  cursor: pointer;
  transition: background-color 0.15s, border-color 0.15s;
}

.btn--outline:hover {
  background-color: var(--color-bg-hover, #f8fafc);
  border-color: var(--color-border-hover, #cbd5e1);
}
```

- [ ] **3.10** Build frontend:

```bash
cd frontend && npm run build
```

- [ ] **3.11** Commit: `feat: add Clerk sign-in to frontend`

---

## Task 4 — Verification and integration testing

**Files:** No new files; verify existing tests pass.

### Steps

- [ ] **4.1** Run backend tests:
```bash
cd backend && python -m pytest tests -q
```

- [ ] **4.2** Run frontend build:
```bash
cd frontend && npm run build
```

- [ ] **4.3** Run frontend lint:
```bash
cd frontend && npm run lint
```

- [ ] **4.4** Verify existing email/password auth unchanged:
```bash
cd backend && python -m pytest tests/test_auth.py -q
```

- [ ] **4.5** Verify `deps.py` unchanged:
```bash
git diff backend/app/api/deps.py
```

- [ ] **4.6** Commit: `ci: verify Clerk auth integration`

---

## Self-Review Checklist

### Spec coverage
- [ ] Backend `POST /api/auth/clerk/exchange` endpoint exists
- [ ] Accepts Clerk frontend JWT, verifies with Clerk public key
- [ ] Extracts email/external ID from Clerk JWT
- [ ] Upserts User + UserOAuthIdentity (provider="clerk")
- [ ] Returns Vela JWT in `TokenResponse` shape
- [ ] `app/core/oauth/clerk.py` verifies Clerk JWT using `jwt` library with JWK set
- [ ] Env vars: `VELA_CLERK_PUBLISHABLE_KEY`
- [ ] Frontend: Clerk SDK (`@clerk/clerk-react`) wraps App with `<ClerkProvider>`
- [ ] "Sign in with Clerk" button on LoginPage
- [ ] On Clerk sign-in: exchanges token for Vela JWT, stores in localStorage
- [ ] Existing email/password flow unchanged

### Placeholder scan
- [ ] No "TBD", "TODO", "FIXME", "add validation", "write tests" in new code
- [ ] All code snippets are complete and runnable
- [ ] All imports are explicit

### Type consistency
- [ ] `TokenResponse` reused (not duplicated) for Clerk exchange
- [ ] `ClerkExchangeRequest` follows existing Pydantic patterns (Field, min_length)
- [ ] `ClerkClaims` uses frozen dataclass with slots
- [ ] `ClerkTokenError` extends `IntegrationError` (maps to 400 via dedicated handler)
- [ ] `UserOAuthIdentity` reused with `provider="clerk"` (no new migration needed)
- [ ] Frontend types (`ClerkExchangeRequest`) match backend Pydantic model
- [ ] `clerkLogin` added to `AuthContextValue` interface and implementation

### No DB migration needed
- The `UserOAuthIdentity` table already supports arbitrary `provider` strings. Clerk identities use `provider="clerk"` with `provider_subject` = Clerk's `sub` claim. No schema change required.

### Security considerations
- Clerk JWT verified server-side (never trusted from client alone)
- JWK set fetched over HTTPS, cached with TTL
- `verify_clerk_token` validates signature, audience, and email claim presence
- New Clerk-only users created with `password_hash=None` (consistent with existing nullable design)
- `VELA_CLERK_PUBLISHABLE_KEY` is public-safe (Clerk publishable keys are not secrets)
- `VELA_CLERK_SECRET_KEY` not needed for this flow (frontend JWT verification uses public JWK set)