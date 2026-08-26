import { useCallback, useMemo, useState } from 'react'
import {
  formatApiError,
  getImageAvailability,
  removeContainer,
  runContainerFromSource,
  startContainer,
  stopContainer,
  type BuildOverride,
  type RunFromSourceRequest,
  type ScalingPolicyRequest,
} from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import BuildConfigModal from './containers/BuildConfigModal'
import {
  buildOverrideFromAnalysis,
  isNeedsBuildOverrideError,
} from './containers/buildOverride'
import { ContainersFormMessageBanner } from './containers/ContainersFormMessageBanner'
import { ContainersRunAdvancedFields } from './containers/ContainersRunAdvancedFields'
import {
  ContainersRunFormFields,
  ContainersRunGitFields,
} from './containers/ContainersRunFormFields'
import { validateScalingPolicy } from './containers/scalingPolicyUtils'
import { DeployProjectSelect } from './containers/DeployProjectSelect'
import { DeploySourceCombobox } from './containers/DeploySourceCombobox'
import { Toast } from '../components/Toast'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import type { FormMessage } from './containers/types'
import { selectionShowsGitBranch } from './containers/deploySourceTypes'
import { useWorkloadGroups } from './containers/useWorkloadGroups'
import { useDeploySourceSelection } from './containers/useDeploySourceSelection'
import { useDeployProjects } from './containers/useDeployProjects'
import { useGitSourceAnalysis } from './containers/useGitSourceAnalysis'
import { useImageRefAvailability } from './containers/useImageRefAvailability'
import {
  createEmptyEnvRow,
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
  const [envRows, setEnvRows] = useState<EnvVarRow[]>([createEmptyEnvRow()])
  const [volumeRows, setVolumeRows] = useState<VolumeMountRow[]>([
    createEmptyVolumeMountRow(),
  ])
  const [startCommand, setStartCommand] = useState('')
  const [scalingPolicy, setScalingPolicy] = useState<ScalingPolicyRequest | null>(null)
  const [buildOverride, setBuildOverride] = useState<BuildOverride | null>(null)
  const [buildConfigOpen, setBuildConfigOpen] = useState(false)
  const [buildConfigInitial, setBuildConfigInitial] = useState<BuildOverride | null>(
    null,
  )
  const [retryRunAfterConfirm, setRetryRunAfterConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<FormMessage | null>(null)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [portError, setPortError] = useState<string | null>(null)
  const [volumeError, setVolumeError] = useState<string | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null)
  const deploySource = useDeploySourceSelection()
  const showGitBranch = selectionShowsGitBranch(deploySource.selection)

  const handleContainerPortChange = useCallback((value: string) => {
    setPortError(null)
    setContainerPort(value)
  }, [])

  const gitAnalysisSetters = useMemo(
    () => ({
      setGitBranch,
      setContainerPort: handleContainerPortChange,
      setContainerName,
      setEnvRows,
      setStartCommand,
    }),
    [handleContainerPortChange]
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

  const scalingValidationError = useMemo(
    () => (scalingPolicy ? validateScalingPolicy(scalingPolicy) : null),
    [scalingPolicy],
  )

  function resetAdvancedFields() {
    setEnvRows([createEmptyEnvRow()])
    setVolumeRows([createEmptyVolumeMountRow()])
    setStartCommand('')
    setScalingPolicy(null)
    setBuildOverride(null)
  }

  function closeBuildConfigModal() {
    setBuildConfigOpen(false)
    setRetryRunAfterConfirm(false)
  }

  function openBuildConfigModal(options: {
    initial?: BuildOverride | null
    retryOnConfirm?: boolean
  }) {
    setBuildConfigInitial(options.initial ?? buildOverride)
    setRetryRunAfterConfirm(options.retryOnConfirm ?? false)
    setBuildConfigOpen(true)
  }

  type VolumeRowIssue = {
    message: string
    rowIndex: number
    field: 'folder' | 'target'
  }

  function validateVolumeRows(): VolumeRowIssue | null {
    for (const [index, row] of volumeRows.entries()) {
      const target = row.target.trim()
      const hasUpload = Boolean(row.uploadId)
      const hasTarget = Boolean(target)
      if (!hasUpload && !hasTarget) {
        continue
      }
      if (row.uploading) {
        return {
          message: 'Wait for folder uploads to finish before deploying.',
          rowIndex: index,
          field: 'folder',
        }
      }
      if (!hasUpload) {
        return {
          message: `Choose a folder for volume ${index + 1}.`,
          rowIndex: index,
          field: 'folder',
        }
      }
      if (!hasTarget) {
        return {
          message: `Enter a container path for volume ${index + 1}.`,
          rowIndex: index,
          field: 'target',
        }
      }
      if (!target.startsWith('/')) {
        return {
          message: `Volume ${index + 1} target must start with /.`,
          rowIndex: index,
          field: 'target',
        }
      }
    }
    return null
  }

  function handleVolumeRowsChange(rows: VolumeMountRow[]) {
    setVolumeError(null)
    setVolumeRows(rows)
  }

  function applyDeploySuggestion(
    suggestion: Parameters<typeof deploySource.applySuggestion>[0]
  ) {
    deploySource.applySuggestion(suggestion)
    setSourceError(null)
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

  async function onAnalyzeGitSource() {
    const selection = deploySource.selection
    if (selection?.kind !== 'git') {
      return
    }
    const analysis = await gitAnalysis.runAnalysis(
      selection.url,
      gitBranch.trim() || 'main',
    )
    if (analysis?.needs_manual_build_config) {
      openBuildConfigModal({
        initial: buildOverrideFromAnalysis(analysis),
        retryOnConfirm: false,
      })
    }
  }

  function buildRunRequest(
    container_port: number,
    override: BuildOverride | null = buildOverride,
  ): RunFromSourceRequest | null {
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
      build_override: override,
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
      default: {
        const _exhaustive: never = selection
        return _exhaustive
      }
    }
  }

  async function executeRun(override: BuildOverride | null = buildOverride) {
    const parsedPort = parseInt(containerPort.trim(), 10)
    if (
      Number.isNaN(parsedPort) ||
      parsedPort < 1 ||
      parsedPort > 65535
    ) {
      setMessage(null)
      setPortError('Enter a container port between 1 and 65535.')
      document.getElementById('container-port-input')?.focus()
      return
    }

    const volumeIssue = validateVolumeRows()
    if (volumeIssue) {
      setMessage(null)
      setVolumeError(volumeIssue.message)
      document
        .getElementById(`volume-${volumeIssue.field}-${volumeIssue.rowIndex + 1}`)
        ?.focus()
      return
    }

    if (scalingValidationError) {
      setMessage({ type: 'err', text: scalingValidationError })
      return
    }

    setBusy(true)
    setMessage(null)
    try {
      const requestBody = buildRunRequest(parsedPort, override)
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
      const scalingWarning =
        typeof response.scaling_policy_warning === 'string' &&
        response.scaling_policy_warning.length > 0
          ? ` ${response.scaling_policy_warning}`
          : ''
      const publicUrl =
        typeof response.public_url === 'string' &&
        response.public_url.length > 0
          ? response.public_url
          : undefined
      setMessage({
        type: 'ok',
        text: `Started (${response.kind}) as ${response.container.name} — image ${response.image}.${routeNote}${scalingWarning}`,
        publicUrl,
      })
      deploySource.clearSelection()
      setContainerName('')
      setGitBranch('main')
      setContainerPort('80')
      resetAdvancedFields()
      await refresh()
    } catch (error) {
      if (isNeedsBuildOverrideError(error)) {
        openBuildConfigModal({
          initial: override,
          retryOnConfirm: true,
        })
        return
      }
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const selection = deploySource.selection
    if (!selection) {
      setMessage(null)
      setSourceError('Choose a deploy source from the search results.')
      document.getElementById('deploy-source-input')?.focus()
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
            setImageRefCheck({
              status: 'unavailable',
              ref: availability.ref,
              canAttemptDeploy: availability.can_attempt_deploy === true,
            })
            if (!availability.can_attempt_deploy) {
              setMessage(null)
              document.getElementById('deploy-source-input')?.focus()
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

    await executeRun(buildOverride)
  }

  async function onBuildConfigConfirm(override: BuildOverride) {
    setBuildOverride(override)
    const shouldRetry = retryRunAfterConfirm
    closeBuildConfigModal()
    if (shouldRetry) {
      await executeRun(override)
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

  function onRemove(containerId: string) {
    setPendingRemoveId(containerId)
  }

  async function confirmPendingRemove() {
    const containerId = pendingRemoveId
    if (!containerId) {
      return
    }
    setRowBusy(containerId)
    setMessage(null)
    try {
      await removeContainer(containerId, true)
      await refresh()
    } catch (error) {
      setMessage({ type: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
      setPendingRemoveId(null)
    }
  }

  const pendingRemoveContainer = pendingRemoveId
    ? groups.find((group) => group.base.id === pendingRemoveId)?.base
    : undefined
  const pendingRemoveBusy =
    pendingRemoveId !== null && rowBusy === pendingRemoveId

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
          pastedGithubRepoPending={deploySource.pastedGithubRepoPending}
          pastedGithubHint={deploySource.pastedGithubHint}
          imageRefCheck={imageRefCheck}
          onInputChange={(value) => {
            setSourceError(null)
            deploySource.onInputChange(value)
          }}
          onInputFocus={deploySource.onInputFocus}
          onPickSuggestion={applyDeploySuggestion}
          onRequestImageCheck={runImageRefAvailabilityCheck}
          onCommitPastedGithubRepo={() => {
            const committed = deploySource.tryCommitPastedGithubRepo()
            if (committed) {
              applyDeploySuggestion(committed)
            }
          }}
          onListClose={() => deploySource.setListOpen(false)}
        />
        {sourceError ? (
          <p
            id="deploy-source-error"
            className="containers-source-check containers-source-check--err"
            role="alert"
          >
            {sourceError}
          </p>
        ) : null}
        <DeployProjectSelect
          projects={deployProjects.projects}
          selectedProjectId={deployProjects.selectedProjectId}
          onSelectedProjectIdChange={deployProjects.setSelectedProjectId}
          loading={deployProjects.loading}
          error={deployProjects.error}
        />
        {showGitBranch ? (
          <ContainersRunGitFields
            containerName={containerName}
            onContainerNameChange={setContainerName}
            containerPort={containerPort}
            onContainerPortChange={handleContainerPortChange}
            portError={portError}
            gitBranch={gitBranch}
            onGitBranchChange={setGitBranch}
            gitAnalysisLoading={gitAnalysis.analysisLoading}
            gitAnalysisError={gitAnalysis.analysisError}
            onAnalyzeGit={() => void onAnalyzeGitSource()}
          />
        ) : (
          <ContainersRunFormFields
            containerName={containerName}
            onContainerNameChange={setContainerName}
            containerPort={containerPort}
            onContainerPortChange={handleContainerPortChange}
            portError={portError}
          />
        )}
        <ContainersRunAdvancedFields
          envRows={envRows}
          onEnvRowsChange={setEnvRows}
          volumeRows={volumeRows}
          onVolumeRowsChange={handleVolumeRowsChange}
          volumeError={volumeError}
          startCommand={startCommand}
          onStartCommandChange={setStartCommand}
          scalingPolicy={scalingPolicy}
          onScalingPolicyChange={setScalingPolicy}
          scalingValidationError={scalingValidationError}
        />

        <div className="containers-form__actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={busy}
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

      <BuildConfigModal
        open={buildConfigOpen}
        initial={buildConfigInitial}
        onCancel={closeBuildConfigModal}
        onConfirm={(override) => {
          void onBuildConfigConfirm(override)
        }}
      />

      <ConfirmDialog
        open={pendingRemoveId !== null}
        title="Remove container?"
        message={
          pendingRemoveContainer
            ? `This permanently removes ${pendingRemoveContainer.name}. This cannot be undone.`
            : 'This permanently removes the container. This cannot be undone.'
        }
        confirmLabel={pendingRemoveBusy ? 'Removing…' : 'Remove'}
        busy={pendingRemoveBusy}
        onConfirm={() => void confirmPendingRemove()}
        onClose={() => setPendingRemoveId(null)}
      />
    </section>
  )
}
