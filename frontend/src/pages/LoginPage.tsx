import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, apiRequest, formatApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

/**
 * Resolves a requested redirect path to a safe application path.
 *
 * @param rawNext - The encoded redirect path to evaluate
 * @returns The decoded path if it starts with `/`; otherwise, `/containers`
 */
function safeNextPath(rawNext: string | null): string {
  if (!rawNext) return '/containers'
  try {
    const decoded = decodeURIComponent(rawNext)
    return decoded.startsWith('/') ? decoded : '/containers'
  } catch {
    return '/containers'
  }
}

/**
 * Renders the sign-in page with email/password and optional Clerk authentication.
 *
 * @returns The sign-in page interface.
 */
export default function LoginPage() {
  const { login, clerkLogin, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [clerkBusy, setClerkBusy] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [clerkConfig, setClerkConfig] = useState<{
    publishableKey: string
    frontendApi: string
  } | null>(null)
  const clerkLoaded = useRef(false)

  const params = new URLSearchParams(location.search)
  const nextPath = safeNextPath(params.get('next'))

  useEffect(() => {
    let cancelled = false
    apiRequest<{
      clerk_enabled: boolean
      clerk_publishable_key: string | null
      clerk_frontend_api: string | null
    }>(
      '/api/auth/config',
      { method: 'GET' },
      { skipAuth: true }
    )
      .then(data => {
        if (
          cancelled
          || !data.clerk_enabled
          || !data.clerk_publishable_key
          || !data.clerk_frontend_api
        ) {
          return
        }
        setClerkConfig({
          publishableKey: data.clerk_publishable_key,
          frontendApi: data.clerk_frontend_api,
        })
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (status === 'authenticated') {
      navigate(nextPath, { replace: true })
    }
  }, [status, navigate, nextPath])

  useEffect(() => {
    if (!clerkConfig) return

    const loadClerk = () => {
      if (clerkLoaded.current) return Promise.resolve()
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

  function onClerkClick() {
    const clerk = (window as any).Clerk
    if (clerk) {
      clerk.redirectToSignIn({
        afterSignInUrl: `${window.location.origin}/login${location.search}`,
      })
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
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {clerkConfig ? (
          <>
            <div className="auth-form__divider">
              <hr className="auth-form__divider-line" />
              <span className="auth-form__divider-text">or</span>
            </div>
            <button
              type="button"
              className="btn btn--outline auth-form__clerk"
              disabled={submitting || clerkBusy}
              onClick={onClerkClick}
            >
              Sign in with Clerk
            </button>
          </>
        ) : null}

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
