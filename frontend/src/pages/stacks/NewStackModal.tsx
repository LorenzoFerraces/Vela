import { useEffect, useId, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { FileText, GitBranch, SlidersHorizontal } from '@phosphor-icons/react'
import { useNavigate } from 'react-router-dom'
import {
  analyzeRepo,
  createStack,
  formatApiError,
  parseManifest,
  type StackServiceCreate,
} from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog'
import { sourceLooksLikeGitUrl } from '../containers/deploySourceTypes'
import ServiceReviewStep from './ServiceReviewStep'

export type NewStackModalProps = {
  open: boolean
  onClose: () => void
  onCreated: (stackName: string) => void
}

type Step = 'source' | 'file' | 'repo' | 'review'
type SourceKind = 'file' | 'repo'

type SourceOptionProps = {
  icon: typeof FileText
  label: string
  description: string
  checked: boolean
  onClick: () => void
}

function SourceOption({ icon: Icon, label, description, checked, onClick }: SourceOptionProps) {
  return (
    <button
      type="button"
      className={`new-stack-modal__source-card${checked ? ' new-stack-modal__source-card--selected' : ''}`}
      role="radio"
      aria-checked={checked}
      onClick={onClick}
    >
      <Icon size={28} weight="duotone" aria-hidden="true" />
      <strong>{label}</strong>
      <span>{description}</span>
    </button>
  )
}

function stackNameFromSource(source: string): string {
  const value = source.trim().replace(/[?#].*$/, '').replace(/\/+$/, '')
  const segment = value.includes(':') && !value.includes('://')
    ? value.slice(value.lastIndexOf(':') + 1).split('/').pop()
    : value.split('/').pop()
  return (segment || '').replace(/\.git$/, '')
}

function originLabel(manifestKind: 'compose' | 'k8s'): string {
  return manifestKind === 'compose' ? 'From Docker Compose manifest' : 'From Kubernetes manifests'
}

export default function NewStackModal({ open, onClose, onCreated }: NewStackModalProps) {
  const navigate = useNavigate()
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const onCloseRef = useRef(onClose)
  const requestCloseRef = useRef(() => {})
  const [step, setStep] = useState<Step>('source')
  const [sourceKind, setSourceKind] = useState<SourceKind | null>(null)
  const [stackName, setStackName] = useState('')
  const [manifestContent, setManifestContent] = useState('')
  const [fileName, setFileName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [services, setServices] = useState<StackServiceCreate[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [origin, setOrigin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [readingFile, setReadingFile] = useState(false)
  const [working, setWorking] = useState(false)
  const [discardOpen, setDiscardOpen] = useState(false)

  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) {
      return
    }
    setStep('source')
    setSourceKind(null)
    setStackName('')
    setManifestContent('')
    setFileName('')
    setRepoUrl('')
    setBranch('main')
    setServices([])
    setWarnings([])
    setOrigin('')
    setError(null)
    setReadingFile(false)
    setWorking(false)
    setDiscardOpen(false)
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    return () => previouslyFocused?.focus()
  }, [open])

  useEffect(() => {
    if (!open) {
      return
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        requestCloseRef.current()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (!open) {
    return null
  }

  const busy = readingFile || working
  const hasChanges = Boolean(
    manifestContent.trim() || fileName || repoUrl.trim() || services.length > 0,
  )

  function requestClose() {
    if (busy) {
      return
    }
    if (hasChanges) {
      setDiscardOpen(true)
      return
    }
    onCloseRef.current()
  }

  requestCloseRef.current = requestClose

  function closeAndOpenBuilder() {
    if (busy) {
      return
    }
    onCloseRef.current()
    navigate('/stacks/new')
  }

  function selectSource(kind: SourceKind) {
    setSourceKind(kind)
    setStep(kind)
    setError(null)
  }

  function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) {
      return
    }
    setFileName(file.name)
    if (!stackName.trim()) {
      setStackName(file.name.replace(/\.(ya?ml)$/i, ''))
    }
    setReadingFile(true)
    setError(null)
    const reader = new FileReader()
    reader.onload = () => {
      setManifestContent(typeof reader.result === 'string' ? reader.result : '')
      setReadingFile(false)
    }
    reader.onerror = () => {
      setError('Unable to read that file. Paste the manifest content instead.')
      setReadingFile(false)
    }
    reader.readAsText(file)
  }

  async function handleParse() {
    if (!manifestContent.trim()) {
      setError('Enter manifest content or upload a file.')
      return
    }
    setWorking(true)
    setError(null)
    try {
      const result = await parseManifest({ yaml_content: manifestContent })
      setServices(result.services)
      setWarnings(result.warnings)
      setOrigin(originLabel(result.manifest_kind))
      setStep('review')
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setWorking(false)
    }
  }

  async function handleAnalyze() {
    if (!sourceLooksLikeGitUrl(repoUrl)) {
      setError('Enter a Git repository URL starting with https://, http://, ssh://, or git@.')
      return
    }
    setWorking(true)
    setError(null)
    try {
      const result = await analyzeRepo({
        git_url: repoUrl.trim(),
        git_branch: branch.trim() || 'main',
      })
      if (!stackName.trim()) {
        setStackName(stackNameFromSource(repoUrl))
      }
      setServices(result.services)
      setWarnings(result.warnings)
      setOrigin(
        result.manifest_kind === 'llm'
          ? 'AI-generated — review carefully'
          : result.manifest_path
            ? `From ${result.manifest_path}`
            : originLabel(result.manifest_kind),
      )
      setStep('review')
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setWorking(false)
    }
  }

  function handleBackFromInput() {
    if (hasChanges) {
      setDiscardOpen(true)
      return
    }
    setStep('source')
    setSourceKind(null)
    setError(null)
  }

  async function handleCreate() {
    if (!stackName.trim()) {
      setError('Enter a stack name.')
      return
    }
    if (services.length === 0) {
      setError('Add at least one service.')
      return
    }
    setWorking(true)
    setError(null)
    try {
      await createStack({ name: stackName.trim(), services })
      onCreated(stackName.trim())
      onCloseRef.current()
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setWorking(false)
    }
  }

  const progress =
    step === 'file'
      ? 'Step 2 of 3 · From a file'
      : step === 'repo'
        ? 'Step 2 of 3 · From a repo'
        : step === 'review'
          ? 'Step 3 of 3 · Review'
          : null

  return (
    <>
      <div className="stacks-modal-backdrop" role="presentation" onClick={requestClose}>
        <div
          ref={dialogRef}
          className="stacks-modal new-stack-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          onClick={(event) => event.stopPropagation()}
        >
          <header className="stacks-modal__header">
            <h2 id={titleId} className="stacks-modal__title">
              New Stack
            </h2>
            {progress ? <p className="new-stack-modal__progress">{progress}</p> : null}
          </header>

          {step === 'source' ? (
            <div className="stacks-modal__body">
              <p className="stacks-modal__lead">How would you like to start?</p>
              <div className="new-stack-modal__source-options" role="radiogroup" aria-label="Stack source">
                <SourceOption
                  icon={FileText}
                  label="From a file"
                  description="Import a Compose or Kubernetes manifest."
                  checked={sourceKind === 'file'}
                  onClick={() => selectSource('file')}
                />
                <SourceOption
                  icon={GitBranch}
                  label="From a repo"
                  description="Analyze a Git repository for services."
                  checked={sourceKind === 'repo'}
                  onClick={() => selectSource('repo')}
                />
                <SourceOption
                  icon={SlidersHorizontal}
                  label="Manual"
                  description="Build a stack service by service."
                  checked={false}
                  onClick={closeAndOpenBuilder}
                />
              </div>
            </div>
          ) : null}

          {step === 'file' ? (
            <div className="stacks-modal__body">
              <div className="containers-form__stack">
                <label className="containers-form__label" htmlFor="new-stack-file-name">
                  Stack name
                </label>
                <input
                  id="new-stack-file-name"
                  className="containers-form__input"
                  autoComplete="off"
                  placeholder="my-stack"
                  value={stackName}
                  onChange={(event) => setStackName(event.target.value)}
                />
              </div>
              <div className="containers-form__stack">
                <label className="containers-form__label" htmlFor="new-stack-manifest-content">
                  Manifest content
                </label>
                <textarea
                  id="new-stack-manifest-content"
                  className="containers-form__input new-stack-modal__manifest"
                  rows={12}
                  value={manifestContent}
                  onChange={(event) => setManifestContent(event.target.value)}
                  spellCheck={false}
                />
                <input
                  ref={fileInputRef}
                  id="new-stack-manifest-file"
                  className="containers-form__folder-input"
                  type="file"
                  accept=".yml,.yaml,text/yaml,application/x-yaml"
                  onChange={handleFileSelected}
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={busy}
                >
                  Upload file
                </button>
              </div>
              {error ? <p className="settings-banner settings-banner--err" role="alert">{error}</p> : null}
              <footer className="stacks-modal__footer">
                <button type="button" className="btn btn--ghost" onClick={handleBackFromInput} disabled={busy}>
                  Back
                </button>
                <button type="button" className="btn btn--primary" onClick={handleParse} disabled={busy}>
                  {working ? 'Parsing…' : 'Parse'}
                </button>
              </footer>
            </div>
          ) : null}

          {step === 'repo' ? (
            <div className="stacks-modal__body">
              <div className="containers-form__stack">
                <label className="containers-form__label" htmlFor="new-stack-repo-url">
                  Git repository URL
                </label>
                <input
                  id="new-stack-repo-url"
                  className="containers-form__input"
                  type="url"
                  autoComplete="url"
                  placeholder="https://github.com/org/repo"
                  value={repoUrl}
                  onChange={(event) => setRepoUrl(event.target.value)}
                />
                {error ? <p className="settings-banner settings-banner--err" role="alert">{error}</p> : null}
                {error ? (
                  <button type="button" className="btn btn--ghost" onClick={closeAndOpenBuilder} disabled={busy}>
                    Open manual builder
                  </button>
                ) : null}
              </div>
              <div className="containers-form__stack">
                <label className="containers-form__label" htmlFor="new-stack-repo-branch">
                  Git branch
                </label>
                <input
                  id="new-stack-repo-branch"
                  className="containers-form__input"
                  type="text"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  placeholder="main"
                />
              </div>
              <footer className="stacks-modal__footer">
                <button type="button" className="btn btn--ghost" onClick={handleBackFromInput} disabled={busy}>
                  Back
                </button>
                <button type="button" className="btn btn--primary" onClick={handleAnalyze} disabled={busy}>
                  {working ? 'Cloning & analyzing…' : 'Analyze repo'}
                </button>
              </footer>
            </div>
          ) : null}

          {step === 'review' ? (
            <ServiceReviewStep
              stackName={stackName}
              services={services}
              warnings={warnings}
              originLabel={origin}
              creating={working}
              error={error}
              onChangeStackName={setStackName}
              onChangeServices={setServices}
              onBack={requestClose}
              onCreate={() => void handleCreate()}
            />
          ) : null}
        </div>
      </div>
      <ConfirmDialog
        open={discardOpen}
        title="Discard changes?"
        message="Your stack setup will be lost."
        confirmLabel="Discard"
        onConfirm={() => {
          setDiscardOpen(false)
          onCloseRef.current()
        }}
        onClose={() => setDiscardOpen(false)}
      />
    </>
  )
}
