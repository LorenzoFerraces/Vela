import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, formatApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const MIN_PASSWORD_LENGTH = 8

export default function RegisterPage() {
  const { register, status } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)

  useEffect(() => {
    if (status === 'authenticated') {
      navigate('/containers', { replace: true })
    }
  }, [status, navigate])

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setErrorText(null)
    if (password.length < MIN_PASSWORD_LENGTH) {
      setErrorText(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    setSubmitting(true)
    try {
      await register({ email: email.trim(), password })
      navigate('/containers', { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setErrorText('That email is already registered.')
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
        <h1 className="auth-card__title">Create your Vela account</h1>
        <form className="auth-form" onSubmit={onSubmit} noValidate>
          <label className="auth-form__label" htmlFor="register-email">
            Email
          </label>
          <input
            id="register-email"
            className="auth-form__input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />

          <label className="auth-form__label" htmlFor="register-password">
            Password
          </label>
          <input
            id="register-password"
            className="auth-form__input"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby="register-password-hint"
          />
          <p id="register-password-hint" className="auth-form__hint">
            Use at least {MIN_PASSWORD_LENGTH} characters.
          </p>

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
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-form__footer">
          Already have an account?{' '}
          <Link className="auth-form__footer-link" to="/login">
            Sign in
          </Link>
        </p>
      </section>
    </main>
  )
}
