import { useCallback, useEffect, useRef, useState } from 'react'
import {
  formatApiError,
  removeContainer,
  startContainer,
  stopContainer,
} from '../api/client'
import { useActiveDeployJobs } from '../hooks/useActiveDeployJobs'
import ConfirmDialog from '../components/ConfirmDialog'
import BuildConfigModal from './containers/BuildConfigModal'
import { ContainersFormMessageBanner } from './containers/ContainersFormMessageBanner'
import { ContainersRunAdvancedFields } from './containers/ContainersRunAdvancedFields'
import {
  ContainersRunFormFields,
  ContainersRunGitFields,
} from './containers/ContainersRunFormFields'
import { DeployProjectSelect } from './containers/DeployProjectSelect'
import { DeploySourceCombobox } from './containers/DeploySourceCombobox'
import { Toast } from '../components/Toast'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import { useWorkloadGroups } from './containers/useWorkloadGroups'
import { useContainerRunForm } from './containers/useContainerRunForm'
import '../deploy-progress.css'

const DEPLOY_JOB_DISCOVERY_POLL_MS = 1000

export default function ContainersPage() {
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null)

  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const runForm = useContainerRunForm({ refresh: () => refreshRef.current() })
  const {
    applyDeploySuggestion,
    buildConfigInitial,
    buildConfigOpen,
    busy,
    closeBuildConfigModal,
    containerName,
    containerPort,
    cpuLimit,
    deployProjects,
    deploySource,
    envRows,
    gitAnalysis,
    gitBranch,
    handleContainerPortChange,
    handleVolumeRowsChange,
    imageRefCheck,
    memoryLimit,
    message,
    onAnalyzeGitSource,
    onBuildConfigConfirm,
    onSubmit,
    pendingJobId,
    portError,
    resolveDeployJob,
    runImageRefAvailabilityCheck,
    scalingPolicy,
    scalingValidationError,
    setContainerName,
    setCpuLimit,
    setEnvRows,
    setGitBranch,
    setMemoryLimit,
    setMessage,
    setScalingPolicy,
    setSourceError,
    setStartCommand,
    showGitBranch,
    sourceError,
    startCommand,
    volumeError,
    volumeRows,
  } = runForm

  const { jobs: deployJobs, refresh: refreshDeployJobs } = useActiveDeployJobs()
  const containerJobs = deployJobs.filter(
    (job) => job.kind === 'container' && job.status === 'in_progress',
  )
  const hasInFlightJob = containerJobs.length > 0

  // ponytail: 1s poll — the hook only fetches on mount and at a 2.5s cadence
  // while it already knows about in-flight jobs, so a deploy submitted via the
  // API or another tab would never appear here, and a just-submitted form job
  // would sit on the 2.5s cadence before resolving. Skipped when background
  // jobs are in flight and the form isn't pending (the hook covers that).
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      if (hasInFlightJob && pendingJobId === null) return
      void refreshDeployJobs()
    }, DEPLOY_JOB_DISCOVERY_POLL_MS)
    return () => window.clearInterval(interval)
  }, [hasInFlightJob, pendingJobId, refreshDeployJobs])

  useEffect(() => {
    if (!pendingJobId) return
    const job = deployJobs.find((entry) => entry.job_id === pendingJobId)
    if (job && job.status !== 'in_progress') {
      resolveDeployJob(job)
      void refreshDeployJobs()
    }
  }, [deployJobs, pendingJobId, resolveDeployJob, refreshDeployJobs])

  // Terminal jobs leave the filtered list on the next poll; refresh the
  // workloads table on that in-flight → none transition so the finished
  // container's row appears even when the form didn't submit the job.
  const workloadsRefreshRef = useRef<() => void>(() => {})
  const hadInFlightJobRef = useRef(false)
  useEffect(() => {
    if (hadInFlightJobRef.current && !hasInFlightJob) {
      workloadsRefreshRef.current()
    }
    hadInFlightJobRef.current = hasInFlightJob
  }, [hasInFlightJob])

  const reportListLoadError = useCallback(
    (detail: string) => {
      setMessage({ type: 'err', text: detail })
    },
    [setMessage],
  )

  const { groups, listLoading, refresh } = useWorkloadGroups(reportListLoadError)
  refreshRef.current = refresh

  useEffect(() => {
    workloadsRefreshRef.current = () => {
      void refresh({ revalidate: true })
    }
  }, [refresh])

  const onStart = useCallback(
    async (containerId: string) => {
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
    },
    [refresh, setMessage],
  )

  const onStop = useCallback(
    async (containerId: string) => {
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
    },
    [refresh, setMessage],
  )

  const onRemove = useCallback(
    (containerId: string) => setPendingRemoveId(containerId),
    [],
  )

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
            gitLlmFallbackAvailable={gitAnalysis.llmFallbackAvailable}
            onRetryWithDefault={() => void onAnalyzeGitSource(true)}
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
          cpuLimit={cpuLimit}
          onCpuLimitChange={setCpuLimit}
          memoryLimit={memoryLimit}
          onMemoryLimitChange={setMemoryLimit}
        />

        <div className="containers-form__actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={busy || !deployProjects.selectedProjectId}
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
        deployJobs={containerJobs}
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
