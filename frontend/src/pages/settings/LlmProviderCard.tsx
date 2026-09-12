import { useEffect, useState } from 'react'
import {
  deleteLlmProvider,
  formatApiError,
  getGeminiConfigStatus,
  getLlmProvider,
  putLlmProvider,
  testLlmProvider,
  type LlmProviderKind,
} from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog'

const PROVIDER_LABELS: Record<LlmProviderKind, string> = {
  openai_compatible: 'OpenAI-compatible',
  gemini: 'Gemini',
  anthropic: 'Anthropic',
}

const PROVIDER_DEFAULTS: Record<
  LlmProviderKind,
  { baseUrl: string; model: string }
> = {
  openai_compatible: { baseUrl: 'https://api.openai.com/v1', model: '' },
  gemini: { baseUrl: '', model: 'gemini-3.5-flash' },
  anthropic: { baseUrl: '', model: 'claude-sonnet-4-5' },
}

const CUSTOM_MODEL_VALUE = '__custom__'

type LlmProviderCardProps = {
  onChanged?: () => void
}

export default function LlmProviderCard({ onChanged }: LlmProviderCardProps) {
  const [provider, setProvider] = useState<LlmProviderKind>('openai_compatible')
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [modelOptions, setModelOptions] = useState<string[] | null>(null)
  const [hasSavedRow, setHasSavedRow] = useState(false)
  const [savedHasKey, setSavedHasKey] = useState(false)
  const [serverConfigured, setServerConfigured] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'test' | 'save' | 'remove' | null>(null)
  const [message, setMessage] = useState<
    { tone: 'ok' | 'err'; text: string } | null
  >(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    void Promise.allSettled([
      getLlmProvider(),
      getGeminiConfigStatus(),
    ]).then(([providerResult, statusResult]) => {
      if (cancelled) {
        return
      }
      if (providerResult.status === 'fulfilled') {
        const row = providerResult.value
        if (row) {
          setProvider(row.provider)
          setBaseUrl(row.base_url ?? PROVIDER_DEFAULTS[row.provider].baseUrl)
          setModel(row.model)
          setSavedHasKey(row.has_key)
          setHasSavedRow(true)
        }
      } else {
        setLoadError(formatApiError(providerResult.reason))
      }
      if (statusResult.status === 'fulfilled') {
        setServerConfigured(statusResult.value.configured)
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

  const effectiveModel = model.trim()
  const canTest =
    !loading &&
    busy === null &&
    apiKey.trim() !== '' &&
    effectiveModel !== '' &&
    (provider !== 'openai_compatible' || baseUrl.trim() !== '')
  const canSave =
    !loading &&
    busy === null &&
    effectiveModel !== '' &&
    (provider !== 'openai_compatible' || baseUrl.trim() !== '')

  function handleProviderChange(next: LlmProviderKind) {
    setProvider(next)
    setBaseUrl(PROVIDER_DEFAULTS[next].baseUrl)
    setModel(PROVIDER_DEFAULTS[next].model)
    setModelOptions(null)
    setMessage(null)
  }

  async function handleTest() {
    setBusy('test')
    setMessage(null)
    try {
      const result = await testLlmProvider({
        provider,
        base_url:
          provider === 'openai_compatible' ? baseUrl.trim() || null : null,
        api_key: apiKey.trim(),
        model: effectiveModel,
      })
      setModelOptions(result.models ?? [])
      setMessage({ tone: 'ok', text: 'Provider reachable.' })
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  async function handleSave() {
    setBusy('save')
    setMessage(null)
    try {
      await putLlmProvider({
        provider,
        base_url:
          provider === 'openai_compatible' ? baseUrl.trim() || null : null,
        model: effectiveModel,
        api_key: apiKey.trim() || undefined,
      })
      const updated = await getLlmProvider()
      setSavedHasKey(Boolean(updated?.has_key))
      setHasSavedRow(true)
      setMessage({ tone: 'ok', text: 'LLM provider saved.' })
      onChanged?.()
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  async function handleRemoveConfirm() {
    setBusy('remove')
    setMessage(null)
    try {
      await deleteLlmProvider()
      setProvider('openai_compatible')
      setBaseUrl(PROVIDER_DEFAULTS.openai_compatible.baseUrl)
      setModel(PROVIDER_DEFAULTS.openai_compatible.model)
      setApiKey('')
      setModelOptions(null)
      setHasSavedRow(false)
      setSavedHasKey(false)
      setMessage({ tone: 'ok', text: 'LLM provider removed.' })
      setConfirmRemoveOpen(false)
      onChanged?.()
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <div>
          <h3 className="settings-card__title">LLM provider</h3>
          <p className="settings-card__subtitle">
            Bring your own key. Your provider overrides the server default
            when set.
          </p>
        </div>
      </div>
      <div className="settings-card__body">
        {loading ? (
          <p className="settings-card__muted">Loading…</p>
        ) : (
          <>
            {hasSavedRow ? (
              <p className="settings-card__muted">
                Your key is active — it overrides the server default.
              </p>
            ) : serverConfigured === true ? (
              <p className="settings-card__muted">
                Server default is configured. Add your own key to take
                priority.
              </p>
            ) : serverConfigured === false ? (
              <p className="settings-card__muted">
                No AI provider is configured yet.
              </p>
            ) : null}
            {loadError ? (
              <p className="settings-banner settings-banner--err" role="alert">
                {loadError}
              </p>
            ) : null}
            {message ? (
              <p
                className={
                  message.tone === 'ok'
                    ? 'settings-banner settings-banner--ok'
                    : 'settings-banner settings-banner--err'
                }
                role={message.tone === 'err' ? 'alert' : 'status'}
              >
                {message.text}
              </p>
            ) : null}
            <div className="settings-form">
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-provider">
                  Provider
                </label>
                <select
                  id="llm-provider"
                  className="settings-form__input"
                  value={provider}
                  disabled={loading || busy !== null}
                  onChange={(event) =>
                    handleProviderChange(event.target.value as LlmProviderKind)
                  }
                >
                  {(Object.keys(PROVIDER_LABELS) as LlmProviderKind[]).map(
                    (kind) => (
                      <option key={kind} value={kind}>
                        {PROVIDER_LABELS[kind]}
                      </option>
                    )
                  )}
                </select>
              </div>
              {provider === 'openai_compatible' ? (
                <div className="settings-form__field">
                  <label className="settings-form__label" htmlFor="llm-base-url">
                    Base URL
                  </label>
                  <input
                    id="llm-base-url"
                    className="settings-form__input"
                    value={baseUrl}
                    disabled={loading || busy !== null}
                    onChange={(event) => setBaseUrl(event.target.value)}
                  />
                </div>
              ) : null}
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-api-key">
                  API key
                </label>
                <input
                  id="llm-api-key"
                  className="settings-form__input"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  disabled={loading || busy !== null}
                  placeholder={
                    savedHasKey ? 'Saved — leave blank to keep' : 'sk-…'
                  }
                  onChange={(event) => setApiKey(event.target.value)}
                />
              </div>

              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-model">
                  Model
                </label>
                {modelOptions !== null ? (
                  <>
                    <select
                      id="llm-model"
                      className="settings-form__input"
                      value={
                        modelOptions.includes(model) ? model : CUSTOM_MODEL_VALUE
                      }
                      disabled={loading || busy !== null}
                      onChange={(event) => {
                        const value = event.target.value
                        if (value !== CUSTOM_MODEL_VALUE) {
                          setModel(value)
                        }
                      }}
                    >
                      {modelOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                      <option value={CUSTOM_MODEL_VALUE}>Custom…</option>
                    </select>
                    {modelOptions.includes(model) ? null : (
                      <input
                        className="settings-form__input"
                        value={model}
                        disabled={loading || busy !== null}
                        aria-label="Custom model name"
                        onChange={(event) => setModel(event.target.value)}
                      />
                    )}
                  </>
                ) : (
                  <input
                    id="llm-model"
                    className="settings-form__input"
                    value={model}
                    disabled={loading || busy !== null}
                    placeholder={
                      PROVIDER_DEFAULTS[provider].model || 'model-name'
                    }
                    onChange={(event) => setModel(event.target.value)}
                  />
                )}
              </div>
            </div>
            <div className="settings-card__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => void handleTest()}
                disabled={!canTest}
              >
                {busy === 'test' ? 'Testing…' : 'Test'}
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void handleSave()}
                disabled={!canSave}
              >
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
              {hasSavedRow ? (
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={() => setConfirmRemoveOpen(true)}
                >
                  {busy === 'remove' ? 'Removing…' : 'Remove'}
                </button>
              ) : null}
            </div>
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirmRemoveOpen}
        title="Remove LLM provider?"
        message="Your key will be deleted. AI analysis falls back to the server default."
        confirmLabel={busy === 'remove' ? 'Removing…' : 'Remove'}
        busy={busy === 'remove'}
        onConfirm={() => void handleRemoveConfirm()}
        onClose={() => setConfirmRemoveOpen(false)}
      />
    </div>
  )
}
