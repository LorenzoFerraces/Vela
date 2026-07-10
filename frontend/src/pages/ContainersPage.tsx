import { useCallback, useMemo, useState } from 'react'
import {
  formatApiError,
  getImageAvailability,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
  type RunFromSourceRequest,
} from '../api/client'
import { ContainersFormMessageBanner } from './containers/ContainersFormMessageBanner'
import { ContainersRunAdvancedFields } from './containers/ContainersRunAdvancedFields'
import { ContainersRunFormFields } from './containers/ContainersRunFormFields'
import { DeployProjectSelect } from './containers/DeployProjectSelect'
import { DeploySourceCombobox } from './containers/DeploySourceCombobox'
import { Toast } from '../components/Toast'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import type { FormMessage } from './containers/types'
import {
  selectionNeedsRegistryCheck,
  selectionShowsGitBranch,
} from './containers/deploySourceTypes'
import { useContainerList } from './containers/useContainerList'
import { useDeploySourceSelection } from './containers/useDeploySourceSelection'
import { useDeployProjects } from './containers/useDeployProjects'
import { useGitSourceAnalysis } from './containers/useGitSourceAnalysis'
import { useImageRefAvailability } from './containers/useImageRefAvailability'
import {
  createEmptyVolumeMountRow,
  parseStartCommand,
  recordFromEnvRows,
  volumesFromRows,
  type EnvVarRow,
  type VolumeMountRow,
} from './containers/runFormAdvanced'

// Memoize key components for performance
const MemoizedWorkloadsTable = React.memo(WorkloadsTable, (prevProps, nextProps) => {
  return (
    prevProps.listLoading === nextProps.listLoading &&
    prevProps.rowBusyId === nextProps.rowBusyId &&
    // Only re-render if rows change significantly
    JSON.stringify(prevProps.rows) === JSON.stringify(nextProps.rows)
  )
})

const MemoizedContainersFormMessageBanner = React.memo(ContainersFormMessageBanner)

export default function ContainersPage() {
  const [containerName, setContainerName] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [containerPort, setContainerPort] = useState('80')
  const [envRows, setEnvRows] = useState<EnvVarRow[]>([{ key: '', value: '' }])
  const [volumeRows, setVolumeRows] = useState<VolumeMountRow[]>([
    createEmptyVolumeMountRow(),
  ])
  const [startCommand, setStartCommand] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const deploySource = useDeploySourceSelection()
  const showGitBranch = selectionShowsGitBranch(deploySource.selection)
  const imageRefAvailability = useImageRefAvailability(deploySource.selection)
  const gitAnalysis = useGitSourceAnalysis(deploySource.selection)
  const projects = useDeployProjects()
  const containers = useContainerList()
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)

  const containerPortNumber = useMemo(() => {
    const num = Number(containerPort)
    return isNaN(num) ? 80 : num
  }, [containerPort])

  const containerPortValid = useMemo(() => {
    const num = Number(containerPort)
    return !isNaN(num) && num > 0 && num < 65536
  }, [containerPort])

  const runSource = useMemo<RunFromSourceRequest | null>(() => {
    if (!deploySource.selection) {
      return null
    }
    const base: RunFromSourceRequest = {
      source_kind: deploySource.selection.kind,
      source: deploySource.selection.ref,
      container_name: containerName || null,
      container_port: containerPortNumber,
      git_branch: gitBranch,
      env_vars: recordFromEnvRows(envRows),
      command: parseStartCommand(startCommand),
      volumes: volumesFromRows(volumeRows),
    }
    if (deploySource.selection.kind === 'image') {
      base.image_ref = deploySource.selection.ref
    } else if (deploySource.selection.kind === 'git') {
      base.git_url = deploySource.selection.ref
    } else if (deploySource.selection.kind === 'dockerfile_template') {
      base.dockerfile_template_id = deploySource.selection.id
    }
    return base
  }, [
    deploySource.selection,
    containerName,
    containerPortNumber,
    gitBranch,
    envRows,
    startCommand,
    volumeRows,
  ])

  const runSourceValid = useMemo(() => {
    if (!runSource) {
      return false
    }
    if (runSource.source_kind === 'image') {
      return runSource.image_ref != null && runSource.image_ref.trim() !== ''
    }
    if (runSource.source_kind === 'git') {
      return runSource.git_url != null && runSource.git_url.trim() !== ''
    }
    if (runSource.source_kind === 'dockerfile_template') {
      return runSource.dockerfile_template_id != null
    }
    return false
  }, [runSource])

  const onSubmit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault()
      if (!runSource || !projects.selectedProject) {
        return
      }
      setBusy(true)
      setMessage(null)
      try {
        const response = await runContainerFromSource({
          ...runSource,
          project_id: projects.selectedProject.id,
        })
        setMessage({
          type: 'success',
          text: `Deployed ${response.container.name}.`,
        })
        // Reset form
        setContainerName('')
        setEnvRows([{ key: '', value: '' }])
        setVolumeRows([createEmptyVolumeMountRow()])
        setStartCommand('')
        // Refresh container list
        containers.refresh()
      } catch (error) {
        setMessage({
          type: 'error',
          text: formatApiError(error),
        })
      } finally {
        setBusy(false)
      }
    },
    [runSource, projects.selectedProject, containers],
  )

  const handleStart = useCallback(
    async (containerId: string) => {
      setRowBusy(containerId)
      try {
        await startContainer(containerId)
        containers.refresh()
      } catch (error) {
        setMessage({
          type: 'error',
          text: formatApiError(error),
        })
      } finally {
        setRowBusy(null)
      }
    },
    [containers],
  )

  const handleStop = useCallback(
    async (containerId: string) => {
      setRowBusy(containerId)
      try {
        await stopContainer(containerId)
        containers.refresh()
      } catch (error) {
        setMessage({
          type: 'error',
          text: formatApiError(error),
        })
      } finally {
        setRowBusy(null)
      }
    },
    [containers],
  )

  const handleRemove = useCallback(
    async (containerId: string) => {
      if (!window.confirm('Remove this container?')) {
        return
      }
      setRowBusy(containerId)
      try {
        await removeContainer(containerId)
        containers.refresh()
      } catch (error) {
        setMessage({
          type: 'error',
          text: formatApiError(error),
        })
      } finally {
        setRowBusy(null)
      }
    },
    [containers],
  )

  const handleDismissMessage = useCallback(() => {
    setMessage(null)
  }, [])

  const handleDismissToast = useCallback(() => {
    setToast(null)
  }, [])

  const handleImageCheck = useCallback(async () => {
    if (!deploySource.selection || deploySource.selection.kind !== 'image') {
      return
    }
    try {
      await getImageAvailability(deploySource.selection.ref)
    } catch (error) {
      setMessage({
        type: 'error',
        text: formatApiError(error),
      })
    }
  }, [deploySource.selection])

  // Add caching to the container list fetching
  const containerList = useMemo(() => {
    return containers.list
  }, [containers.list])

  const containerListLoading = useMemo(() => {
    return containers.loading
  }, [containers.loading])

  return (
    <div className="containers-page">
      <header className="containers-page__header">
        <h1 className="containers-page__title">Deploy</h1>
        <p className="containers-page__lead">
          Deploy a container from an image, Git repository, or Dockerfile template.
        </p>
      </header>

      <div className="containers-page__form">
        <form onSubmit={onSubmit}>
          <div className="containers-form-row">
            <DeploySourceCombobox
              selection={deploySource.selection}
              setSelection={deploySource.setSelection}
              imageRefAvailability={imageRefAvailability}
              gitAnalysis={gitAnalysis}
            />
          </div>

          {selectionNeedsRegistryCheck(deploySource.selection) ? (
            <div className="containers-form-row">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={handleImageCheck}
                disabled={busy}
              >
                Check registry
              </button>
            </div>
          ) : null}

          {showGitBranch ? (
            <div className="containers-form-row">
              <label className="containers-form-label">
                Git branch
                <input
                  type="text"
                  className="containers-form-input"
                  value={gitBranch}
                  onChange={(event) => setGitBranch(event.target.value)}
                  disabled={busy}
                  placeholder="main"
                />
              </label>
            </div>
          ) : null}

          <div className="containers-form-row">
            <DeployProjectSelect
              projects={projects.list}
              selectedProject={projects.selectedProject}
              setSelectedProject={projects.setSelectedProject}
              loading={projects.loading}
            />
          </div>

          <div className="containers-form-row">
            <label className="containers-form-label">
              Container name (optional)
              <input
                type="text"
                className="containers-form-input"
                value={containerName}
                onChange={(event) => setContainerName(event.target.value)}
                disabled={busy}
                placeholder="my-container"
              />
            </label>
          </div>

          <div className="containers-form-row">
            <label className="containers-form-label">
              Container port
              <input
                type="number"
                className="containers-form-input"
                value={containerPort}
                onChange={(event) => setContainerPort(event.target.value)}
                disabled={busy}
                min="1"
                max="65535"
                placeholder="80"
              />
            </label>
          </div>

          <ContainersRunFormFields
            envRows={envRows}
            setEnvRows={setEnvRows}
            volumeRows={volumeRows}
            setVolumeRows={setVolumeRows}
            startCommand={startCommand}
            setStartCommand={setStartCommand}
          />

          <div className="containers-form-row">
            <button
              type="submit"
              className="btn btn--primary btn--lg"
              disabled={busy || !runSourceValid}
            >
              {busy ? 'Deploying…' : 'Deploy'}
            </button>
          </div>
        </form>
      </div>

      <div className="containers-page__table">
        <h2 className="containers-page__section-title">Deployed containers</h2>
        <MemoizedWorkloadsTable
          listLoading={containerListLoading}
          rows={containerList}
          rowBusyId={rowBusy}
          onStart={handleStart}
          onStop={handleStop}
          onRemove={handleRemove}
        />
      </div>

      <MemoizedContainersFormMessageBanner
        message={message}
        onDismiss={handleDismissMessage}
      />

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onDismiss={handleDismissToast}
        />
      )}
    </div>
  )
}