import { useCallback, useEffect, useState } from 'react'
import {
  type EmailNotificationPreferences,
  type EmailNotificationPreferencesUpdate,
  formatApiError,
  getEmailNotificationPreferences,
  updateEmailNotificationPreferences,
  type AlertHistoryEntry,
  getAlertHistory,
} from '../api/client'

export function EmailNotificationSettingsCard() {
  const [preferences, setPreferences] = useState<EmailNotificationPreferences | null>(null)
  const [alertHistory, setAlertHistory] = useState<AlertHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const loadPreferences = useCallback(async () => {
    try {
      setError(null)
      const prefs = await getEmailNotificationPreferences()
      setPreferences(prefs)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      setHistoryError(null)
      const history = await getAlertHistory({ limit: 10 })
      setAlertHistory(history)
    } catch (err) {
      setHistoryError(formatApiError(err))
    }
  }, [])

  useEffect(() => {
    void loadPreferences()
  }, [loadPreferences])

  async function handleSave(updates: EmailNotificationPreferencesUpdate) {
    if (!preferences) return
    setBusy(true)
    setError(null)
    try {
      const updated = await updateEmailNotificationPreferences(updates)
      setPreferences(updated)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  async function toggleAlerts() {
    if (!preferences) return
    await handleSave({ alerts_enabled: !preferences.alerts_enabled })
  }

  async function toggleAlertType(type: 'stop' | 'failure' | 'unhealthy') {
    if (!preferences) return
    const newTypes = preferences.alert_types.includes(type)
      ? preferences.alert_types.filter((t) => t !== type)
      : [...preferences.alert_types, type]
    await handleSave({ alert_types: newTypes })
  }

  function toggleShowHistory() {
    setShowHistory(!showHistory)
    if (!showHistory) {
      void loadHistory()
    }
  }

  const alertTypeLabels: Record<'stop' | 'failure' | 'unhealthy', string> = {
    stop: 'Container stopped',
    failure: 'Container failed',
    unhealthy: 'Container unhealthy',
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <div>
          <h3 className="settings-card__title">Email Alerts</h3>
          <p className="settings-card__subtitle">
            Get notified when your containers have issues.
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

        {preferences ? (
          <div className="settings-form">
            <label className="settings-form__checkbox">
              <input
                type="checkbox"
                checked={preferences.alerts_enabled}
                onChange={() => void toggleAlerts()}
                disabled={busy}
              />
              <span>Enable email alerts</span>
            </label>

            {preferences.alerts_enabled ? (
              <>
                <div className="settings-form__field">
                  <label className="settings-form__label" htmlFor="alert-email">
                    Email address
                  </label>
                  <input
                    id="alert-email"
                    type="email"
                    value={preferences.email}
                    readOnly
                    className="settings-form__input settings-form__input--readonly"
                  />
                  <p className="settings-form__hint">
                    Alerts are sent to your account email. Change it in your account settings.
                  </p>
                </div>

                <div className="settings-form__group">
                  <span className="settings-form__label">Alert types</span>
                  <ul className="settings-form__checkbox-list">
                    {(Object.keys(alertTypeLabels) as Array<'stop' | 'failure' | 'unhealthy'>).map(
                      (type) => (
                        <li key={type}>
                          <label className="settings-form__checkbox">
                            <input
                              type="checkbox"
                              checked={preferences.alert_types.includes(type)}
                              onChange={() => void toggleAlertType(type)}
                              disabled={busy}
                            />
                            <span>{alertTypeLabels[type]}</span>
                          </label>
                        </li>
                      ),
                    )}
                  </ul>
                </div>

                <p className="settings-form__hint">
                  Alerts are sent immediately when an issue is detected.
                </p>

                <div className="settings-card__actions">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={toggleShowHistory}
                  >
                    {showHistory ? 'Hide' : 'Show'} recent alerts
                  </button>
                </div>

                {showHistory && historyError ? (
                  <p className="settings-banner settings-banner--err" role="alert">
                    {historyError}
                  </p>
                ) : null}

                {showHistory && !historyError && alertHistory.length > 0 ? (
                  <div className="alert-history">
                    <h4 className="alert-history__title">Recent Alerts</h4>
                    <ul className="alert-history__list">
                      {alertHistory.map((alert) => (
                        <li key={alert.id} className="alert-history__item">
                          <div className="alert-history__event">
                            <span className="alert-history__type">{alert.event_type}</span>
                            <span className="alert-history__container">
                              {alert.container_id}
                            </span>
                          </div>
                          <div className="alert-history__meta">
                            <span
                              className={
                                alert.status === 'sent'
                                  ? 'alert-history__status alert-history__status--sent'
                                  : 'alert-history__status alert-history__status--failed'
                              }
                            >
                              {alert.status}
                            </span>
                            <time className="alert-history__time">
                              {new Date(alert.sent_at).toLocaleString()}
                            </time>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : showHistory && !historyError ? (
                  <p className="settings-card__muted">No recent alerts</p>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
