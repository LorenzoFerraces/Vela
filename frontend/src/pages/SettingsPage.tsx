import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  type GithubStatus,
  disconnectGithub,
  formatApiError,
  getAccessToken,
  getAiPrefillPreferences,
  getGeminiConfigStatus,
  getGithubAuthorizeUrl,
  getGithubStatusWithRetry,
  patchAiPrefillPreferences,
  type AiPrefillPreferences,
} from '../api/client'
import { EmailNotificationSettingsCard } from '../components/EmailNotificationSettings'

type StatusState =
  | { kind: 'loading' }
  | { kind: 'ready'; status: GithubStatus }
  | { kind: 'error'; detail: string }

type Banner = { tone: 'ok' | 'err'; text: string } | null

const oauthErrorReasonMessages: Record<string, string> = {
  access_denied: 'GitHub authorization was cancelled.',
  invalid_state: 'The authorization link expired. Please try connecting again.',
  bad_verification_code: 'GitHub rejected the authorization. Try connecting again.',
  missing_params: 'GitHub did not return the expected parameters.',
  network_error: 'Could not reach GitHub. Check your connection and try again.',
  account_already_linked:
    'This GitHub account is already linked to another Vela user. Disconnect it there or sign in as that user.',
}

function describeOAuthError(reason: string | null, message: string | null): string {
  if (!reason) {
    return message ?? 'GitHub authorization failed.'
  }
  const friendly = oauthErrorReasonMessages[reason]
  if (friendly) return friendly
  return message ?? `GitHub authorization failed (${reason}).`
}

function formatJoinedDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export default function SettingsPage() {
  const { user, status: authStatus } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [state, setState] = useState<StatusState>({ kind: 'loading' })
  const [banner, setBanner] = useState<Banner>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async (options?: { showLoading?: boolean }) => {
    if (!getAccessToken()) {
      return
    }
    const showLoading = options?.showLoading !== false
    if (showLoading) {
      setState({ kind: 'loading' })
    }
    try {
      const status = await getGithubStatusWithRetry()
      setState({ kind: 'ready', status })
    } catch (error) {
      setState({ kind: 'error', detail: formatApiError(error) })
    }
  }, [])

  useEffect(() => {
    if (authStatus !== 'authenticated' || !user?.id) {
      return
    }
    void reload({ showLoading: true })
  }, [reload, authStatus, user?.id])

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState !== 'visible') return
      if (authStatus !== 'authenticated' || !user?.id) return
      void reload({ showLoading: false })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [reload, authStatus, user?.id])

  // Surface the redirect outcome from /api/auth/github/callback then drop the params.
  useEffect(() => {
    const githubParam = searchParams.get('github')
    if (!githubParam) return
    if (githubParam === 'connected') {
      setBanner({ tone: 'ok', text: 'GitHub account connected.' })
    } else if (githubParam === 'error') {
      setBanner({
        tone: 'err',
        text: describeOAuthError(searchParams.get('reason'), searchParams.get('message')),
      })
    }
    const next = new URLSearchParams(searchParams)
    next.delete('github')
    next.delete('reason')
    next.delete('message')
    setSearchParams(next, { replace: true })
    if (githubParam === 'connected') {
      void reload({ showLoading: false })
    }
  }, [searchParams, setSearchParams, reload])

  async function handleConnect() {
    setBusy(true)
    setBanner(null)
    try {
      const { authorize_url } = await getGithubAuthorizeUrl()
      window.location.assign(authorize_url)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
      setBusy(false)
    }
  }

  async function handleDisconnect() {
    if (!window.confirm('Disconnect your GitHub account from Vela?')) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await disconnectGithub()
      setBanner({ tone: 'ok', text: 'GitHub account disconnected.' })
      await reload()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="settings-page">
      <h1 className="settings-page__title">Settings</h1>
      <p className="settings-page__lead">
        Account info and third-party integrations.
      </p>

      <h2 className="settings-page__section-title">Account</h2>
      <div className="settings-card">
        <dl className="settings-card__list">
          <div className="settings-card__row">
            <dt>Email</dt>
            <dd>{user?.email ?? '—'}</dd>
          </div>
          <div className="settings-card__row">
            <dt>Member since</dt>
            <dd>{formatJoinedDate(user?.created_at ?? null)}</dd>
          </div>
        </dl>
      </div>

      <h2 className="settings-page__section-title">Integrations</h2>
      {banner ? (
        <p
          className={
            banner.tone === 'ok'
              ? 'settings-banner settings-banner--ok'
              : 'settings-banner settings-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          {banner.text}
        </p>
      ) : null}

      <div className="settings-card">
        <div className="settings-card__header">
          <div>
            <h3 className="settings-card__title">GitHub</h3>
            <p className="settings-card__subtitle">
              Connect your account to deploy private repositories from the
              Containers page.
            </p>
          </div>
        </div>
        {state.kind === 'loading' ? (
          <p className="settings-card__muted">Loading GitHub status…</p>
        ) : state.kind === 'error' ? (
          <p className="settings-banner settings-banner--err" role="alert">
            {state.detail}
          </p>
        ) : state.status.connected ? (
          <ConnectedGithubCard
            status={state.status}
            onDisconnect={handleDisconnect}
            busy={busy}
          />
        ) : (
          <DisconnectedGithubCard onConnect={handleConnect} busy={busy} />
        )}
      </div>

      <AiPrefillSettingsCard />

      <EmailNotificationSettingsCard />
    </section>
  )
}

const AI_PREFILL_LABELS: Record<keyof AiPrefillPreferences, string> = {
  git_branch: 'Git branch',
  container_port: 'Container port',
  container_name: 'Container name',
  env_vars: 'Environment variables',
  start_command: 'Start command',
}

function AiPrefillSettingsCard() {
  const [preferences, setPreferences] = useState<AiPrefillPreferences | null>(
    null
  )
  const [geminiConfigured, setGeminiConfigured] = useState<boolean | null>(
    null
  )
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void Promise.allSettled([
      getAiPrefillPreferences(),
      getGeminiConfigStatus(),
    ]).then((results) => {
      if (cancelled) {
        return
      }
      const [prefsResult, geminiResult] = results
      if (prefsResult.status === 'fulfilled') {
        setPreferences(prefsResult.value)
      } else {
        setError(formatApiError(prefsResult.reason))
      }
      if (geminiResult.status === 'fulfilled') {
        setGeminiConfigured(geminiResult.value.configured)
      } else {
        setError((previous) =>
          previous ?? formatApiError(geminiResult.reason)
        )
      }
    }).finally(() => {
      if (!cancelled) {
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  async function onToggle(field: keyof AiPrefillPreferences, enabled: boolean) {
    if (!preferences) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      const updated = await patchAiPrefillPreferences({ [field]: enabled })
      setPreferences(updated)
    } catch (patchError) {
      setError(formatApiError(patchError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <div>
          <h3 className="settings-card__title">AI deploy analysis</h3>
          <p className="settings-card__subtitle">
            When you pick a GitHub repo, Vela can analyze it and pre-fill the
            run form.
          </p>
        </div>
      </div>
      <div className="settings-card__body">
        {loading ? (
          <p className="settings-card__muted">Loading preferences…</p>
        ) : null}
        {error ? (
          <p className="settings-banner settings-banner--err" role="alert">
            {error}
          </p>
        ) : null}
        {geminiConfigured === false ? (
          <p className="settings-card__muted">
            AI analysis is unavailable until the server sets VELA_GEMINI_API_KEY.
            Deterministic fallbacks may still apply when analyzing repos.
          </p>
        ) : null}
        {preferences ? (
          <ul className="settings-ai-prefill-list">
            {(Object.keys(AI_PREFILL_LABELS) as Array<keyof AiPrefillPreferences>).map(
              (field) => (
                <li key={field} className="settings-ai-prefill-list__row">
                  <label>
                    <input
                      type="checkbox"
                      checked={preferences[field]}
                      disabled={busy}
                      onChange={(event) =>
                        void onToggle(field, event.target.checked)
                      }
                    />
                    {AI_PREFILL_LABELS[field]}
                  </label>
                </li>
              )
            )}
          </ul>
        ) : null}
      </div>
    </div>
  )
}

function DisconnectedGithubCard({
  onConnect,
  busy,
}: {
  onConnect: () => void
  busy: boolean
}) {
  return (
    <div className="settings-card__body">
      <p className="settings-card__muted">
        Vela will request access to your repositories so private builds work
        without you pasting tokens by hand.
      </p>
      <div className="settings-card__actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={onConnect}
          disabled={busy}
        >
          {busy ? 'Redirecting…' : 'Connect GitHub'}
        </button>
      </div>
    </div>
  )
}

function ConnectedGithubCard({
  status,
  onDisconnect,
  busy,
}: {
  status: GithubStatus
  onDisconnect: () => void
  busy: boolean
}) {
  return (
    <div className="settings-card__body">
      <div className="settings-github__profile">
        {status.avatar_url ? (
          <img
            className="settings-github__avatar"
            src={status.avatar_url}
            alt=""
            width={44}
            height={44}
          />
        ) : (
          <div className="settings-github__avatar settings-github__avatar--placeholder" aria-hidden="true">
            GH
          </div>
        )}
        <div>
          <p className="settings-github__login">@{status.login ?? 'unknown'}</p>
          <p className="settings-github__connected-at">
            Connected {formatJoinedDate(status.connected_at)}
          </p>
        </div>
      </div>
      {status.scopes.length > 0 ? (
        <ul className="settings-github__scopes" aria-label="Granted GitHub scopes">
          {status.scopes.map((scope) => (
            <li key={scope} className="settings-github__scope">
              {scope}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="settings-card__actions">
        <button
          type="button"
          className="btn btn--danger"
          onClick={onDisconnect}
          disabled={busy}
        >
          {busy ? 'Working…' : 'Disconnect'}
        </button>
      </div>
    </div>
  )
}
