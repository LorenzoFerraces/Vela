import { useEffect, useState, type FormEvent } from 'react'
import {
  formatApiError,
  getWebhookConfig,
  listWebhookDeliveries,
  setWebhookConfig,
  type WebhookDeliveryPublic,
} from '../../api/client'
import { Skeleton } from '../../components/Skeleton'
import { listPreviews, revokePreview, type PreviewPublic } from '../../api/previews'
import './webhook-settings.css'

type Props = {
  projectId: string
}

type FormState = {
  repo: string
  branchFilters: string
  enabled: boolean
  previewEnabled: boolean
  ttl: string
}

const initialForm: FormState = {
  repo: '',
  branchFilters: '',
  enabled: false,
  previewEnabled: false,
  ttl: '3600',
}

function formatReceivedAt(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export default function WebhookSettings({ projectId }: Props) {
  const [form, setForm] = useState<FormState>(initialForm)
  const [deliveries, setDeliveries] = useState<WebhookDeliveryPublic[]>([])
  const [previews, setPreviews] = useState<PreviewPublic[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [activityError, setActivityError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setConfigError(null)
    setActivityError(null)
    setSaved(false)
    void getWebhookConfig(projectId)
      .then((config) => {
        if (cancelled) return
        setForm({
          repo: config.repo_full_name ?? '',
          branchFilters: config.branch_filters.join(', '),
          enabled: config.enabled,
          previewEnabled: config.preview_enabled,
          ttl: String(config.preview_ttl_seconds),
        })
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setConfigError(formatApiError(loadError))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    void Promise.all([listWebhookDeliveries(projectId), listPreviews(projectId)])
      .then(([history, previewRows]) => {
        if (cancelled) return
        setDeliveries(history)
        setPreviews(previewRows)
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setActivityError(formatApiError(loadError))
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  function update<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [field]: value }))
    setSaved(false)
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    const ttl = Number(form.ttl)
    const repo = form.repo.trim()
    if (repo === '' || !Number.isInteger(ttl) || ttl < 60) {
      setError('Enter a repository and a TTL of at least 60 seconds.')
      setSaved(false)
      return
    }
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await setWebhookConfig(projectId, {
        repo_full_name: repo,
        enabled: form.enabled,
        branch_filters: form.branchFilters
          .split(',')
          .map((branch) => branch.trim())
          .filter((branch) => branch !== ''),
        preview_enabled: form.previewEnabled,
        preview_ttl_seconds: ttl,
      })
      setSaved(true)
    } catch (saveError: unknown) {
      setError(formatApiError(saveError))
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(preview: PreviewPublic) {
    try {
      await revokePreview(projectId, preview.id)
      setPreviews((previous) =>
        previous.map((row) =>
          row.id === preview.id ? { ...row, status: 'closed' } : row,
        ),
      )
    } catch (revokeError: unknown) {
      setError(formatApiError(revokeError))
    }
  }

  return (
    <section className="teams-page__section webhook-settings">
      <h3 className="teams-page__section-title">Webhook</h3>
      {loading ? (
        <Skeleton className="skeleton--hint-line" />
      ) : configError ? (
        <p className="teams-page__hint teams-page__hint--err" role="alert">
          {configError}
        </p>
      ) : (
        <>
          {error ? (
            <p className="teams-page__hint teams-page__hint--err" role="alert">
              {error}
            </p>
          ) : null}
          {saved ? (
            <p className="teams-page__hint" role="status">
              Webhook settings saved.
            </p>
          ) : null}
          <form
            className="teams-page__quota-form webhook-settings__form"
            onSubmit={(event) => void handleSave(event)}
            noValidate
          >
            <label className="teams-page__field teams-page__field--grow">
              Repository
              <input
                className="teams-page__input"
                value={form.repo}
                disabled={busy}
                placeholder="org/repo"
                onChange={(event) => update('repo', event.target.value)}
              />
            </label>
            <label className="teams-page__field teams-page__field--grow">
              Branch filters
              <input
                className="teams-page__input"
                value={form.branchFilters}
                disabled={busy}
                placeholder="main, release/*"
                onChange={(event) =>
                  update('branchFilters', event.target.value)
                }
              />
            </label>
            <label className="teams-page__field">
              Preview TTL (seconds)
              <input
                type="number"
                min="60"
                step="1"
                className="teams-page__input"
                value={form.ttl}
                disabled={busy}
                onChange={(event) => update('ttl', event.target.value)}
              />
            </label>
            <label className="webhook-settings__checkbox">
              <input
                type="checkbox"
                checked={form.enabled}
                disabled={busy}
                onChange={(event) => update('enabled', event.target.checked)}
              />
              Enabled
            </label>
            <label className="webhook-settings__checkbox">
              <input
                type="checkbox"
                checked={form.previewEnabled}
                disabled={busy}
                onChange={(event) =>
                  update('previewEnabled', event.target.checked)
                }
              />
              Preview deployments
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? 'Saving…' : 'Save webhook'}
            </button>
          </form>

          {activityError ? (
            <p className="teams-page__hint teams-page__hint--err" role="alert">
              {activityError}
            </p>
          ) : null}

          <h4 className="teams-page__section-title">Previews</h4>
          {previews.length === 0 ? (
            <p className="teams-page__muted">No previews yet.</p>
          ) : (
            <div className="webhook-deliveries__wrap">
              <table className="webhook-deliveries">
                <thead>
                  <tr>
                    <th scope="col">PR</th>
                    <th scope="col">URL</th>
                    <th scope="col">Expires</th>
                    <th scope="col">Status</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {previews.map((preview) => (
                    <tr key={preview.id}>
                      <td>#{preview.pr_number}</td>
                      <td>
                        {preview.public_url ? (
                          <a href={preview.public_url} target="_blank" rel="noreferrer">
                            {preview.public_url}
                          </a>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>{formatReceivedAt(preview.expires_at)}</td>
                      <td>{preview.status}</td>
                      <td>
                        {preview.status === 'closed' || preview.status === 'expired' ? (
                          '—'
                        ) : (
                          <button
                            type="button"
                            className="btn btn--ghost"
                            onClick={() => void handleRevoke(preview)}
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h4 className="teams-page__section-title">Recent deliveries</h4>
          {deliveries.length === 0 ? (
            <p className="teams-page__muted">No deliveries yet.</p>
          ) : (
            <div className="webhook-deliveries__wrap">
              <table className="webhook-deliveries">
                <thead>
                  <tr>
                    <th scope="col">Event</th>
                    <th scope="col">Branch</th>
                    <th scope="col">Status</th>
                    <th scope="col">Received</th>
                    <th scope="col">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.map((delivery) => (
                    <tr key={delivery.delivery_id}>
                      <td>{delivery.event}</td>
                      <td>{delivery.branch ?? '—'}</td>
                      <td>{delivery.status}</td>
                      <td>{formatReceivedAt(delivery.received_at)}</td>
                      <td>{delivery.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}
