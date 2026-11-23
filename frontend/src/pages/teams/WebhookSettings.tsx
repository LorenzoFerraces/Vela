import { useEffect, useState, type FormEvent } from 'react'
import {
  formatApiError,
  getWebhookConfig,
  listWebhookDeliveries,
  setWebhookConfig,
  type WebhookDeliveryPublic,
} from '../../api/client'
import { Skeleton } from '../../components/Skeleton'
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
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void Promise.all([
      getWebhookConfig(projectId),
      listWebhookDeliveries(projectId),
    ])
      .then(([config, history]) => {
        if (cancelled) return
        setForm({
          repo: config.repo_full_name ?? '',
          branchFilters: config.branch_filters.join(', '),
          enabled: config.enabled,
          previewEnabled: config.preview_enabled,
          ttl: String(config.preview_ttl_seconds),
        })
        setDeliveries(history)
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(formatApiError(loadError))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
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

  return (
    <section className="teams-page__section webhook-settings">
      <h3 className="teams-page__section-title">Webhook</h3>
      {loading ? (
        <Skeleton className="skeleton--hint-line" />
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
