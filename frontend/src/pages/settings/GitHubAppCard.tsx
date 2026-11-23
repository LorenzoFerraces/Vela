import { useEffect, useState } from 'react'
import {
  formatApiError,
  getGithubAppConfig,
  setGithubAppConfig,
} from '../../api/client'
import { Skeleton } from '../../components/Skeleton'

type Banner = { tone: 'ok' | 'err'; text: string } | null

export default function GitHubAppCard() {
  const [appId, setAppId] = useState('')
  const [slug, setSlug] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [hasPrivateKey, setHasPrivateKey] = useState(false)
  const [hasWebhookSecret, setHasWebhookSecret] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)

  useEffect(() => {
    let cancelled = false
    void getGithubAppConfig()
      .then((config) => {
        if (cancelled) return
        setAppId(config.app_id ?? '')
        setSlug(config.slug ?? '')
        setHasPrivateKey(config.has_private_key)
        setHasWebhookSecret(config.has_webhook_secret)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBanner({ tone: 'err', text: formatApiError(error) })
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSave() {
    setBusy(true)
    setBanner(null)
    try {
      const updated = await setGithubAppConfig({
        app_id: appId.trim(),
        slug: slug.trim(),
        private_key: privateKey,
        webhook_secret: webhookSecret,
      })
      setHasPrivateKey(updated.has_private_key)
      setHasWebhookSecret(updated.has_webhook_secret)
      setPrivateKey('')
      setWebhookSecret('')
      setBanner({ tone: 'ok', text: 'Credentials saved.' })
    } catch (error: unknown) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  const canSave =
    !loading &&
    !busy &&
    appId.trim() !== '' &&
    privateKey.trim() !== '' &&
    webhookSecret.trim() !== ''

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <div>
          <h3 className="settings-card__title">App credentials</h3>
          <p className="settings-card__subtitle">
            Credentials for push webhooks. Secrets are stored encrypted and
            never shown again.
          </p>
        </div>
      </div>
      <div className="settings-card__body">
        {loading ? (
          <Skeleton className="skeleton--hint-line" />
        ) : (
          <>
            {banner ? (
              <p
                className={
                  banner.tone === 'ok'
                    ? 'settings-banner settings-banner--ok'
                    : 'settings-banner settings-banner--err'
                }
                role={banner.tone === 'err' ? 'alert' : 'status'}
              >
                {banner.text}
              </p>
            ) : null}
            <p className="settings-card__muted" role="status">
              Private key: {hasPrivateKey ? 'saved' : 'not set'} · Webhook
              secret: {hasWebhookSecret ? 'saved' : 'not set'}
            </p>
            <div className="settings-form">
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="github-app-id">
                  App ID
                </label>
                <input
                  id="github-app-id"
                  className="settings-form__input"
                  value={appId}
                  disabled={busy}
                  onChange={(event) => setAppId(event.target.value)}
                />
              </div>
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="github-app-slug">
                  Slug
                </label>
                <input
                  id="github-app-slug"
                  className="settings-form__input"
                  value={slug}
                  disabled={busy}
                  onChange={(event) => setSlug(event.target.value)}
                />
              </div>
              <div className="settings-form__field">
                <label
                  className="settings-form__label"
                  htmlFor="github-app-private-key"
                >
                  Private key
                </label>
                <textarea
                  id="github-app-private-key"
                  className="settings-form__input"
                  rows={4}
                  autoComplete="off"
                  spellCheck={false}
                  value={privateKey}
                  disabled={busy}
                  placeholder={
                    hasPrivateKey
                      ? 'Saved — paste a new PEM to replace'
                      : 'Paste PEM contents'
                  }
                  onChange={(event) => setPrivateKey(event.target.value)}
                />
              </div>
              <div className="settings-form__field">
                <label
                  className="settings-form__label"
                  htmlFor="github-app-webhook-secret"
                >
                  Webhook secret
                </label>
                <input
                  id="github-app-webhook-secret"
                  className="settings-form__input"
                  type="password"
                  autoComplete="off"
                  value={webhookSecret}
                  disabled={busy}
                  placeholder={
                    hasWebhookSecret
                      ? 'Saved — enter a new secret to replace'
                      : 'Webhook secret'
                  }
                  onChange={(event) => setWebhookSecret(event.target.value)}
                />
              </div>
            </div>
            <div className="settings-card__actions">
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void handleSave()}
                disabled={!canSave}
              >
                {busy ? 'Saving…' : 'Save credentials'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
