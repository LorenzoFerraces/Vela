import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  deleteStack,
  deployStack,
  formatApiError,
  getStack,
  listStacks,
  updateStack,
  type BuildOverride,
  type Stack,
  type StackService,
  type StackServiceCreate,
} from '../api/client'
import { useActiveDeployJobs } from '../hooks/useActiveDeployJobs'
import type { DeployJob, DeployJobError } from '../api/client'
import BuildConfigModal from './containers/BuildConfigModal'
import NewStackModal from './stacks/NewStackModal'
import './stacks/stacks.css'
import '../deploy-progress.css'

const DEPLOY_JOB_DISCOVERY_POLL_MS = 1000

type Banner = { tone: 'ok' | 'err'; text: string } | null

function stackServiceToCreate(service: StackService): StackServiceCreate {
  return {
    service_name: service.service_name,
    source_kind: service.source_kind,
    source_ref: service.source_ref,
    git_branch: service.git_branch,
    container_port: service.container_port,
    env_vars: service.env_vars,
    command: service.command,
    public_route: service.public_route,
    depends_on: service.depends_on,
    volumes: service.volumes,
    scaling_policy: service.scaling_policy,
    build_override: service.build_override ?? null,
  }
}

function resolveFailedService(
  stack: Stack,
  failedServiceName: string | null,
): StackService | null {
  if (failedServiceName) {
    const named = stack.services.find(
      (service) => service.service_name === failedServiceName,
    )
    if (named) {
      return named
    }
  }
  return (
    stack.services.find(
      (service) => service.source_kind === 'git' && !service.build_override,
    ) ??
    stack.services.find((service) => service.source_kind === 'git') ??
    null
  )
}

function jobNeedsBuildOverride(job: DeployJob): boolean {
  return job.error?.code === 'needs_build_override'
}

function failedServiceFromJob(job: DeployJob): string | null {
  if (job.error?.failed_service) return job.error.failed_service
  return (
    job.services.find((service) => service.state === 'failed')?.name ?? null
  )
}

function StackCard({
  stack,
  busy,
  pendingDelete,
  deployJob,
  onDeploy,
  onDelete,
}: {
  stack: Stack
  busy: boolean
  pendingDelete: string | null
  deployJob: DeployJob | undefined
  onDeploy: (id: string) => void
  onDelete: (id: string) => void
}) {
  const isPending = pendingDelete === stack.id
  const deploying = deployJob !== undefined && deployJob.status === 'in_progress'
  return (
    <article className="stacks-card">
      <div className="stacks-card__top">
        <Link className="stacks-card__name" to={`/stacks/${stack.id}`}>
          {stack.name}
        </Link>
      </div>
      <div className="stacks-card__network">{stack.network_name}</div>
      {deploying && deployJob && deployJob.services.length > 0 ? (
        <ul
          className="stacks-card__services"
          role="status"
          aria-live="polite"
          aria-label={`Deploying ${stack.name}`}
        >
          {deployJob.services.map((service) => (
            <li
              key={service.name}
              className={`stacks-card__service stacks-card__service--${service.state}`}
            >
              <span className="stacks-card__service-dot" aria-hidden="true" />
              <span className="stacks-card__service-name">{service.name}</span>
              {service.state !== 'pending' && service.state !== 'running' ? (
                <span className="stacks-card__service-phase">
                  {service.state}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <div className="stacks-card__meta">
          {stack.services.length}{' '}
          {stack.services.length === 1 ? 'service' : 'services'} ·{' '}
          {new Date(stack.created_at).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
          })}
        </div>
      )}
      <div className="stacks-card__actions">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => onDeploy(stack.id)}
          disabled={deploying || busy}
          aria-busy={deploying}
        >
          {deploying ? 'DEPLOYING…' : 'Deploy'}
        </button>
        <button
          type="button"
          className="btn btn--danger btn--sm"
          onClick={() => onDelete(stack.id)}
          disabled={deploying || busy}
        >
          {isPending ? 'Confirm?' : 'Remove'}
        </button>
      </div>
    </article>
  )
}

function StackCardSkeleton() {
  return (
    <article className="stacks-card stacks-card--skeleton" aria-hidden="true">
      <div className="stacks-card__top">
        <span className="skeleton stacks-card__skeleton-line stacks-card__skeleton-line--name" />
        <span className="skeleton stacks-card__skeleton-line stacks-card__skeleton-line--meta" />
      </div>
      <span className="skeleton stacks-card__skeleton-line stacks-card__skeleton-line--network" />
      <span className="skeleton stacks-card__skeleton-line stacks-card__skeleton-line--meta" />
      <div className="stacks-card__actions">
        <span className="skeleton stacks-card__skeleton-line" />
        <span className="skeleton stacks-card__skeleton-line" />
      </div>
    </article>
  )
}

export default function StacksPage() {
  const [stacks, setStacks] = useState<Stack[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [newStackOpen, setNewStackOpen] = useState(false)
  const [buildConfigOpen, setBuildConfigOpen] = useState(false)
  const [buildConfigInitial, setBuildConfigInitial] = useState<BuildOverride | null>(
    null,
  )
  const [pendingDeployStackId, setPendingDeployStackId] = useState<string | null>(
    null,
  )
  const [pendingServiceName, setPendingServiceName] = useState<string | null>(null)
  const [pendingJobIds, setPendingJobIds] = useState<Record<string, string>>({})
  const deleteTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const { jobs: deployJobs, refresh: refreshDeployJobs } = useActiveDeployJobs()
  const stackJobs = deployJobs.filter((job) => job.kind === 'stack')
  const stackJobsInFlight = stackJobs.some((job) => job.status === 'in_progress')
  const pendingStackJobCount = Object.keys(pendingJobIds).length
  const activeJobFor = (stackId: string) => {
    const jobId = pendingJobIds[stackId]
    return jobId ? stackJobs.find((job) => job.job_id === jobId) : undefined
  }

  const loadStacks = useCallback(async () => {
    try {
      const rows = await listStacks()
      setStacks(rows)
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStacks()
  }, [loadStacks])

  useEffect(() => {
    return () => {
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
    }
  }, [])

  // ponytail: 1s poll — the hook only fetches on mount and at a 2.5s cadence
  // while it already knows about in-flight jobs, so a deploy submitted outside
  // this page's form (API, another tab) would never surface its checklist
  // here, and a just-submitted card job would sit out the 2.5s cadence first.
  // Skipped when background stack jobs are in flight and no card is pending
  // (the hook covers that cadence).
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      if (stackJobsInFlight && pendingStackJobCount === 0) return
      void refreshDeployJobs()
    }, DEPLOY_JOB_DISCOVERY_POLL_MS)
    return () => window.clearInterval(interval)
  }, [stackJobsInFlight, pendingStackJobCount, refreshDeployJobs])

  const openBuildConfigForDeployFailure = useCallback(
    async (stackId: string, error: DeployJobError | null) => {
      try {
        const stack = await getStack(stackId)
        const failedName = error?.failed_service ?? null
        const service = resolveFailedService(stack, failedName)
        if (!service) {
          setBanner({
            tone: 'err',
            text: error?.detail ?? 'Deploy failed.',
          })
          return
        }
        setPendingDeployStackId(stackId)
        setPendingServiceName(service.service_name)
        setBuildConfigInitial(service.build_override ?? null)
        setBuildConfigOpen(true)
        setBanner({
          tone: 'err',
          text: `Build config needed for service '${service.service_name}'.`,
        })
      } catch (loadError) {
        setBanner({ tone: 'err', text: formatApiError(loadError) })
      }
    },
    [],
  )

  const resolvingRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    for (const [stackId, jobId] of Object.entries(pendingJobIds)) {
      if (resolvingRef.current.has(jobId)) continue
      const job = deployJobs.find((entry) => entry.job_id === jobId)
      if (!job || job.status === 'in_progress') continue
      resolvingRef.current.add(jobId)
      setPendingJobIds((prev) => {
        const next = { ...prev }
        delete next[stackId]
        return next
      })
      if (job.status === 'succeeded') {
        setBanner({ tone: 'ok', text: 'Stack deployed.' })
        void loadStacks()
      } else if (job.error && jobNeedsBuildOverride(job)) {
        void openBuildConfigForDeployFailure(stackId, job.error)
      } else {
        const failedService = job.error ? failedServiceFromJob(job) : null
        setBanner({
          tone: 'err',
          text: failedService
            ? `Deploy failed on service '${failedService}'.`
            : job.error?.detail ?? 'Deploy failed.',
        })
        void refreshDeployJobs()
      }
    }
  }, [deployJobs, pendingJobIds, loadStacks, openBuildConfigForDeployFailure, refreshDeployJobs])

  const handleDeploy = useCallback(
    async (id: string) => {
      setBusy(true)
      setBanner(null)
      try {
        const accepted = await deployStack(id)
        setPendingJobIds((prev) => ({ ...prev, [id]: accepted.job_id }))
      } catch (err) {
        setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        setBusy(false)
      }
    },
    [],
  )

  function closeBuildConfigModal() {
    setBuildConfigOpen(false)
    setPendingDeployStackId(null)
    setPendingServiceName(null)
    setBuildConfigInitial(null)
  }

  async function onBuildConfigConfirm(override: BuildOverride) {
    const stackId = pendingDeployStackId
    const serviceName = pendingServiceName
    closeBuildConfigModal()
    if (!stackId || !serviceName) {
      return
    }

    setBusy(true)
    setBanner(null)
    try {
      const stack = await getStack(stackId)
      const services = stack.services.map((service) => {
        const create = stackServiceToCreate(service)
        if (service.service_name === serviceName) {
          return { ...create, build_override: override }
        }
        return create
      })
      await updateStack(stackId, {
        name: stack.name,
        services,
      })
      const accepted = await deployStack(stackId)
      setPendingJobIds((prev) => ({ ...prev, [stackId]: accepted.job_id }))
      return
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = useCallback(async (id: string) => {
    if (pendingDelete === id) {
      setPendingDelete(null)
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
      setBusy(true)
      setBanner(null)
      try {
        await deleteStack(id)
        setStacks((prev) => prev.filter((s) => s.id !== id))
        setBanner({ tone: 'ok', text: 'Stack deleted.' })
      } catch (err) {
        setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        setBusy(false)
      }
    } else {
      setPendingDelete(id)
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
      deleteTimer.current = setTimeout(() => setPendingDelete(null), 5000)
    }
  }, [pendingDelete])

  return (
    <section className="stacks-page">
      <h1 className="containers-page__title">Stacks</h1>
      <p className="containers-page__lead">
        Multi-app stacks — group services on a shared network.
      </p>

      <div className="stacks-page__actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => setNewStackOpen(true)}
        >
          New Stack
        </button>
      </div>

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

      <h2 className="containers-page__subtitle">Your stacks</h2>

      {listLoading && stacks.length === 0 ? (
        <div className="stacks-cards">
          {Array.from({ length: 4 }, (_, index) => (
            <StackCardSkeleton key={index} />
          ))}
        </div>
      ) : stacks.length === 0 ? (
        <div className="stacks-empty">
          <span>No stacks yet.</span>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setNewStackOpen(true)}
          >
            New Stack
          </button>
        </div>
      ) : (
        <div className="stacks-cards">
          {stacks.map((stack) => (
            <StackCard
              key={stack.id}
              stack={stack}
              busy={busy}
              pendingDelete={pendingDelete}
              deployJob={activeJobFor(stack.id)}
              onDeploy={handleDeploy}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <div className="dashboard-page__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setBanner(null)
            void loadStacks()
          }}
          disabled={listLoading}
        >
          Refresh
        </button>
      </div>

      <NewStackModal
        open={newStackOpen}
        onClose={() => setNewStackOpen(false)}
        onCreated={(stackName) => {
          setBanner({ tone: 'ok', text: `Stack '${stackName}' created.` })
          void loadStacks()
        }}
      />

      <BuildConfigModal
        open={buildConfigOpen}
        initial={buildConfigInitial}
        onCancel={closeBuildConfigModal}
        onConfirm={(override) => {
          void onBuildConfigConfirm(override)
        }}
      />
    </section>
  )
}
