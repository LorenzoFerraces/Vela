import { useCallback, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import {
  formatApiError,
  getImageAvailability,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
  type GithubRepo,
} from '../api/client'
import { ContainersFormMessageBanner } from './containers/ContainersFormMessageBanner'
import { ContainersGithubRepoPickerPanel } from './containers/ContainersGithubRepoPickerPanel'
import { ContainersGithubSourceAside } from './containers/ContainersGithubSourceAside'
import { ContainersRunFormFields } from './containers/ContainersRunFormFields'
import { ContainersSourceField } from './containers/ContainersSourceField'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import type { FormMessage } from './containers/types'
import { sourceLooksLikeGitUrl } from './containers/sourceKind'
import { useContainerList } from './containers/useContainerList'
import { useGithubForContainersForm } from './containers/useGithubForContainersForm'
import { useImageRefAvailability } from './containers/useImageRefAvailability'
import { useRunFormSource } from './containers/useRunFormSource'

export default function ContainersPage() {
  const { user, status: authStatus } = useAuth()
  const [containerName, setContainerName] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)

  const {
    source,
    containerPort,
    showGitBranch,
    updateSourceInput,
    setContainerPort,
  } = useRunFormSource()

  const reportListLoadError = useCallback((detail: string) => {
    setMessage({ type: 'err', text: detail })
  }, [])

  const { rows, listLoading, refresh } = useContainerList(reportListLoadError)

  const {
    githubStatus,
    githubReposCache,
    repoPickerOpen,
    repoQuery,
    filteredGithubRepos,
    setRepoQuery,
    toggleRepoPicker,
    setRepoPickerOpen,
  } = useGithubForContainersForm({
    authStatus,
    userId: user?.id,
  })

  const { imageRefCheck, setImageRefCheck, runImageRefAvailabilityCheck } =
    useImageRefAvailability(source)

  function pickRepo(repo: GithubRepo) {
    updateSourceInput(`${repo.html_url}.git`)
    setGitBranch(repo.default_branch || 'main')
    setImageRefCheck({ status: 'idle' })
    setRepoPickerOpen(false)
    setRepoQuery('')
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = source.trim()
    if (!trimmed) {
      setMessage({ type: 'err', text: 'Enter a Docker image or a Git URL.' })
      return
    }
    if (!sourceLooksLikeGitUrl(trimmed)) {
      const alreadyOkForRef =
        imageRefCheck.status === 'ok' && imageRefCheck.ref === trimmed
      if (!alreadyOkForRef) {
        try {
          const availability = await getImageAvailability(trimmed)
          if (availability.checked && !availability.available) {
            const notFoundMessage = availability.can_attempt_deploy
              ? 'Registry did not confirm this image (you may need registry access).'
              : 'Image not found in the registry.'
            setImageRefCheck({
              status: 'unavailable',
              ref: availability.ref,
              canAttemptDeploy: availability.can_attempt_deploy === true,
            })
            if (!availability.can_attempt_deploy) {
              setMessage({ type: 'err', text: notFoundMessage })
              return
            }
          }
          if (availability.checked && availability.available) {
            setImageRefCheck({ status: 'ok', ref: availability.ref })
          }
        } catch (error) {
          setMessage({ type: 'err', text: formatApiError(error) })
          return
        }
      }
    }
    setBusy(true)
    setMessage(null)
    try {
      const parsedPort = parseInt(containerPort.trim(), 10)
      const container_port = Number.isNaN(parsedPort)
        ? showGitBranch
          ? 5173
          : 80
        : parsedPort
      const res = await runContainerFromSource({
        source: trimmed,
        container_name: containerName.trim() || null,
        host_port: null,
        container_port,
        git_branch: gitBranch.trim() || 'main',
        route_host: null,
        route_path_prefix: '/',
        route_tls: false,
        public_route: true,
      })
      const routeNote = res.route_wired
        ? ' Traefik route registered.'
        : ''
      const publicUrl =
        typeof res.public_url === 'string' && res.public_url.length > 0
          ? res.public_url
          : undefined
      setMessage({
        type: 'ok',
        text: `Started (${res.kind}) as ${res.container.name} — image ${res.image}.${routeNote}`,
        publicUrl,
      })
      updateSourceInput('')
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onStart(containerId: string) {
    setRowBusy(containerId)
    setMessage(null)
    try {
      await startContainer(containerId)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onStop(containerId: string) {
    setRowBusy(containerId)
    setMessage(null)
    try {
      await stopContainer(containerId)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onRemove(containerId: string) {
    if (!window.confirm('Remove this container?')) return
    setRowBusy(containerId)
    setMessage(null)
    try {
      await removeContainer(containerId, true)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  return (
    <section className="containers-page">
      <h1 className="containers-page__title">Containers</h1>
      <p className="containers-page__lead">
        Image or Git URL → build and run on the Vela network.
      </p>

      <form
        className="containers-form"
        onSubmit={onSubmit}
        aria-busy={busy}
      >
        <div className="containers-form__source-header">
          <label className="containers-form__label" htmlFor="source-input">
            Image or Git URL
          </label>
          <ContainersGithubSourceAside
            authStatus={authStatus}
            userId={user?.id}
            githubStatus={githubStatus}
            repoPickerOpen={repoPickerOpen}
            onToggleRepoPicker={toggleRepoPicker}
          />
        </div>
        {repoPickerOpen ? (
          <ContainersGithubRepoPickerPanel
            githubReposCache={githubReposCache}
            filteredRepos={filteredGithubRepos}
            repoQuery={repoQuery}
            onRepoQueryChange={setRepoQuery}
            onPickRepo={pickRepo}
          />
        ) : null}
        <ContainersSourceField
          source={source}
          showGitBranch={showGitBranch}
          imageRefCheck={imageRefCheck}
          onSourceChange={updateSourceInput}
          onRequestImageCheck={runImageRefAvailabilityCheck}
        />
        <ContainersRunFormFields
          showGitBranch={showGitBranch}
          containerName={containerName}
          onContainerNameChange={setContainerName}
          gitBranch={gitBranch}
          onGitBranchChange={setGitBranch}
          containerPort={containerPort}
          onContainerPortChange={setContainerPort}
        />

        <div className="containers-form__actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={
              busy ||
              (!showGitBranch &&
                imageRefCheck.status === 'unavailable' &&
                !imageRefCheck.canAttemptDeploy)
            }
          >
            {busy ? 'Building…' : 'Build'}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setMessage(null)
              void refresh()
            }}
            disabled={listLoading || busy}
          >
            Refresh list
          </button>
        </div>
      </form>

      {message ? (
        <ContainersFormMessageBanner
          key={`${message.type}:${message.text}:${message.publicUrl ?? ''}`}
          message={message}
        />
      ) : null}

      <h2 className="containers-page__subtitle">Running workloads</h2>
      <WorkloadsTable
        listLoading={listLoading}
        rows={rows}
        rowBusyId={rowBusy}
        onStart={onStart}
        onStop={onStop}
        onRemove={onRemove}
      />
    </section>
  )
}
