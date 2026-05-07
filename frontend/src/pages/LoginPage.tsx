import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
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
  const { login, status } = useAuth()
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
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {/*
          Future: render OAuth buttons (Google / Microsoft / GitHub) below.
          Each button will navigate to /api/auth/oauth/{provider}/start and
          land back on this page with ?token=...; AuthProvider stays unchanged.
        */}

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
