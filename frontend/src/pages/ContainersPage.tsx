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
import type { ScalingPolicyRequest } from './containers/ContainersRunScalingFields'
import { DeployProjectSelect } from './containers/DeployProjectSelect'
import { DeploySourceCombobox } from './containers/DeploySourceCombobox'
import { Toast } from '../components/Toast'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import type { FormMessage } from './containers/types'
import {
  selectionNeedsRegistryCheck,
  selectionShowsGitBranch,
} from './containers/deploySourceTypes'
import { useWorkloadGroups } from './containers/useWorkloadGroups'
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

export default function ContainersPage() {
  const [containerName, setContainerName] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [containerPort, setContainerPort] = useState('80')
  const [envRows, setEnvRows] = useState<EnvVarRow[]>([{ key: '', value: '' }])
  const [volumeRows, setVolumeRows] = useState<VolumeMountRow[]>([
    createEmptyVolumeMountRow(),
  ])
  const [startCommand, setStartCommand] = useState('')
  const [scalingPolicy, setScalingPolicy] = useState<ScalingPolicyRequest | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const deploySource = useDeploySourceSelection()
  const showGitBranch = selectionShowsGitBranch(deploySource.selection)

  const gitAnalysisSetters = useMemo(
    () => ({
      setGitBranch,
      setContainerPort,
      setContainerName,
      setEnvRows,
      setStartCommand,
    }),
    []
  )

  const gitAnalysis = useGitSourceAnalysis(gitAnalysisSetters)

  const reportListLoadError = useCallback((detail: string) => {
    setMessage({ type: 'err', text: detail })
  }, [])

  const { groups, listLoading, refresh } = useWorkloadGroups(reportListLoadError)
  const deployProjects = useDeployProjects()

  const imageRefForCheck =
    deploySource.selection?.kind === 'image'
      ? deploySource.selection.ref
      : ''

  const { imageRefCheck, setImageRefCheck, runImageRefAvailabilityCheck } =
    useImageRefAvailability(imageRefForCheck)

  function resetAdvancedFields() {
    setEnvRows([{ key: '', value: '' }])
    setVolumeRows([createEmptyVolumeMountRow()])
    setStartCommand('')
    setScalingPolicy(null)
  }

  function validateVolumeRows(): string | null {
    for (const [index, row] of volumeRows.entries()) {
      const target = row.target.trim()
      const hasUpload = Boolean(row.uploadId)
      const hasTarget = Boolean(target)
      if (!hasUpload && !hasTarget) {
        continue
      }
      if (row.uploading) {
        return 'Wait for folder uploads to finish before deploying.'
      }
      if (!hasUpload) {
        return `Choose a folder for volume ${index + 1}.`
      }
      if (!hasTarget) {
        return `Enter a container path for volume ${index + 1}.`
      }
      if (!target.startsWith('/')) {
        return `Volume ${index + 1} target must start with /.`
      }
    }
    return null
  }

  function applyDeploySuggestion(
    suggestion: Parameters<typeof deploySource.applySuggestion>[0]
  ) {
    deploySource.applySuggestion(suggestion)
    if (suggestion.kind === 'git') {
      setGitBranch(suggestion.default_branch || 'main')
      setImageRefCheck({ status: 'idle' })
      resetAdvancedFields()
      gitAnalysis.clearAnalysis()
      return
    }
    gitAnalysis.clearAnalysis()
    resetAdvancedFields()
    setImageRefCheck({ status: 'idle' })
  }

  function onAnalyzeGitSource() {
    const selection = deploySource.selection
    if (selection?.kind !== 'git') {
      return
    }
    void gitAnalysis.runAnalysis(selection.url, gitBranch.trim() || 'main')
  }

  function buildRunRequest(container_port: number): RunFromSourceRequest | null {
    const selection = deploySource.selection
    if (!selection || !deployProjects.selectedProjectId) {
      return null
    }
    const command = parseStartCommand(startCommand)
    const base = {
      container_name: containerName.trim() || null,
      host_port: null,
      container_port,
      git_branch: gitBranch.trim() || 'main',
      route_host: null,
      route_path_prefix: '/',
      route_tls: false,
      public_route: true,
      env_vars: recordFromEnvRows(envRows),
      command,
      volumes: volumesFromRows(volumeRows),
      project_id: deployProjects.selectedProjectId,
      scaling_policy: scalingPolicy,
    }
    switch (selection.kind) {
      case 'image':
        return {
          ...base,
          source_kind: 'image',
          image_ref: selection.ref,
        }
      case 'git':
        return {
          ...base,
          source_kind: 'git',
          git_url: selection.url,
        }
      case 'dockerfile_template':
        return {
          ...base,
          source_kind: 'dockerfile_template',
          dockerfile_template_id: selection.templateId,
        }
    }
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const selection = deploySource.selection
    if (!selection) {
      setMessage({
        type: 'err',
        text: 'Choose a deploy source from the search results.',
      })
      return
    }
    if (selection.kind === 'image') {
      const trimmed = selection.ref
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
    const parsedPort = parseInt(containerPort.trim(), 10)
    if (
      Number.isNaN(parsedPort) ||
      parsedPort < 1 ||
      parsedPort > 65535
    ) {
      setMessage({
        type: 'err',
        text: 'Enter a container port between 1 and 65535.',
      })
      return
    }

    const volumeError = validateVolumeRows()
    if (volumeError) {
      setMessage({ type: 'err', text: volumeError })
      return
    }

    setBusy(true)
    setMessage(null)
    try {
      const requestBody = buildRunRequest(parsedPort)
      if (!requestBody) {
        setMessage({
          type: 'err',
          text: 'Choose a deploy source from the search results.',
        })
        return
      }
      const response = await runContainerFromSource(requestBody)
      const routeNote = response.route_wired
        ? ' Traefik route registered.'
        : ''
      const publicUrl =
        typeof response.public_url === 'string' &&
        response.public_url.length > 0
          ? response.public_url
          : undefined
      setMessage({
        type: 'ok',
        text: `Started (${response.kind}) as ${response.container.name} — image ${response.image}.${routeNote}`,
        publicUrl,
      })
      deploySource.clearSelection()
      setContainerName('')
      setGitBranch('main')
      setContainerPort('80')
      resetAdvancedFields()
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
        Search for a registry image, GitHub repository, or saved Dockerfile, then
        build and run on the Vela network.
      </p>

      <form
        className="containers-form"
        onSubmit={onSubmit}
        aria-busy={busy}
      >
        <label className="containers-form__label" htmlFor="deploy-source-input">
          Deploy source
        </label>
        <DeploySourceCombobox
          listboxId={deploySource.listboxId}
          rootRef={deploySource.rootRef}
          displayValue={deploySource.displayValue}
          selection={deploySource.selection}
          suggestions={deploySource.suggestions}
          listOpen={deploySource.listOpen}
          searchLoading={deploySource.searchLoading}
          imageRefCheck={imageRefCheck}
          onInputChange={deploySource.onInputChange}
          onInputFocus={deploySource.onInputFocus}
          onPickSuggestion={applyDeploySuggestion}
          onRequestImageCheck={runImageRefAvailabilityCheck}
        />
        <DeployProjectSelect
          projects={deployProjects.projects}
          selectedProjectId={deployProjects.selectedProjectId}
          onSelectedProjectIdChange={deployProjects.setSelectedProjectId}
          loading={deployProjects.loading}
          error={deployProjects.error}
        />
        <ContainersRunFormFields
          showGitBranch={showGitBranch}
          containerName={containerName}
          onContainerNameChange={setContainerName}
          containerPort={containerPort}
          onContainerPortChange={setContainerPort}
          gitBranch={gitBranch}
          onGitBranchChange={setGitBranch}
          gitAnalysisLoading={gitAnalysis.analysisLoading}
          gitAnalysisError={gitAnalysis.analysisError}
          onAnalyzeGit={showGitBranch ? onAnalyzeGitSource : undefined}
        />
        <ContainersRunAdvancedFields
          envRows={envRows}
          onEnvRowsChange={setEnvRows}
          volumeRows={volumeRows}
          onVolumeRowsChange={setVolumeRows}
          startCommand={startCommand}
          onStartCommandChange={setStartCommand}
          scalingPolicy={scalingPolicy}
          onScalingPolicyChange={setScalingPolicy}
        />

        <div className="containers-form__actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={
              busy ||
              deployProjects.loading ||
              deployProjects.projects.length === 0 ||
              gitAnalysis.analysisLoading ||
              !deploySource.selection ||
              (selectionNeedsRegistryCheck(deploySource.selection) &&
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
            Refresh
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
        groups={groups}
        rowBusyId={rowBusy}
        onStart={onStart}
        onStop={onStop}
        onRemove={onRemove}
      />

      <Toast
        message={gitAnalysis.successToast}
        onDismiss={gitAnalysis.dismissSuccessToast}
      />
    </section>
  )
}
