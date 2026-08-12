import { useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  formatApiError,
  parseCompose,
  type StackServiceCreate,
} from '../../api/client'
import ComposeImportReviewModal from './ComposeImportReviewModal'
import type { ImportedStackState } from './importTypes'

type Banner = { tone: 'ok' | 'err'; text: string } | null

export default function ComposeImportPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [yaml, setYaml] = useState('')
  const [name, setName] = useState('')
  const [banner, setBanner] = useState<Banner>(null)
  const [parsing, setParsing] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [parsedServices, setParsedServices] = useState<StackServiceCreate[]>([])
  const [warnings, setWarnings] = useState<string[]>([])

  async function handleParse() {
    if (!yaml.trim()) {
      setBanner({ tone: 'err', text: 'Paste or upload a compose file first.' })
      return
    }
    setParsing(true)
    setBanner(null)
    try {
      const result = await parseCompose({ yaml_content: yaml })
      setParsedServices(result.services)
      setWarnings(result.warnings || [])
      setReviewOpen(true)
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setParsing(false)
    }
  }

  function onFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const text = typeof reader.result === 'string' ? reader.result : ''
      setYaml(text)
      if (!name.trim()) {
        const base = file.name.replace(/\.(ya?ml)$/i, '')
        if (base) setName(base)
      }
      setBanner(null)
    }
    reader.onerror = () => {
      setBanner({ tone: 'err', text: 'Could not read that file.' })
    }
    reader.readAsText(file)
  }

  function handleContinue() {
    const stackName = name.trim() || 'imported-stack'
    const state: ImportedStackState = {
      importedStack: { name: stackName, services: parsedServices },
      composeWarnings: warnings,
    }
    navigate('/stacks/new', { state })
  }

  return (
    <section className="stacks-import-page">
      <h1 className="containers-page__title">Import Docker Compose</h1>
      <p className="containers-page__lead">
        Paste or upload a docker-compose.yml, review services, then open the builder.
      </p>

      <form className="containers-form" onSubmit={(e) => e.preventDefault()}>
        <label className="containers-form__label" htmlFor="import-name-input">
          Stack name
        </label>
        <input
          id="import-name-input"
          className="containers-form__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-stack"
        />

        <label className="containers-form__label" htmlFor="import-yaml-input">
          docker-compose.yml content
        </label>
        <textarea
          id="import-yaml-input"
          className="containers-form__input stacks-import-page__yaml"
          value={yaml}
          onChange={(e) => setYaml(e.target.value)}
          placeholder={`version: "3"\nservices:\n  web:\n    image: nginx:alpine`}
        />

        <input
          ref={fileInputRef}
          type="file"
          accept=".yml,.yaml,text/yaml,application/x-yaml"
          className="containers-form__folder-input"
          onChange={onFileSelected}
          tabIndex={-1}
          aria-hidden="true"
        />

        <div className="containers-form__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => fileInputRef.current?.click()}
          >
            Upload file
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void handleParse()}
            disabled={parsing}
          >
            {parsing ? 'Parsing…' : 'Parse'}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => navigate('/stacks')}
          >
            Cancel
          </button>
        </div>
      </form>

      {banner ? (
        <div
          className={
            banner.tone === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      {reviewOpen ? (
        <ComposeImportReviewModal
          stackName={name.trim() || 'imported-stack'}
          services={parsedServices}
          warnings={warnings}
          onChangeServices={setParsedServices}
          onBack={() => setReviewOpen(false)}
          onContinue={handleContinue}
        />
      ) : null}
    </section>
  )
}
