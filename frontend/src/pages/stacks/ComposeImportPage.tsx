import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { importCompose, formatApiError } from '../../api/client'

export default function ComposeImportPage() {
  const navigate = useNavigate()
  const [yaml, setYaml] = useState('')
  const [name, setName] = useState('')
  const [banner, setBanner] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  async function handleImport() {
    try {
      const result = await importCompose({
        name: name || 'imported-stack',
        yaml_content: yaml,
      })
      if (result.warnings?.length) {
        setWarnings(result.warnings)
      } else {
        navigate('/stacks')
      }
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    }
  }

  return (
    <section className="stacks-import-page">
      <h1 className="containers-page__title">Import Docker Compose</h1>
      <p className="containers-page__lead">
        Paste a docker-compose.yml file to create a stack.
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
          className="containers-form__input"
          value={yaml}
          onChange={(e) => setYaml(e.target.value)}
          placeholder={`version: "3"\nservices:\n  web:\n    image: nginx:alpine`}
        />

        <div className="containers-form__actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleImport}
          >
            Import
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
          className="containers-banner containers-banner--err"
          role="alert"
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <div className="containers-banner containers-banner--ok">
          <p className="containers-banner__text">
            Imported with warnings:
          </p>
          <ul className="containers-banner__list">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => navigate('/stacks')}
          >
            Continue to stacks
          </button>
        </div>
      ) : null}
    </section>
  )
}
