import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  formatApiError,
  getProjectComputeQuota,
  getUsageSummary,
  type ProjectComputeQuota,
  type UsageSummary,
} from '../../api/client'
import { formatBytes } from '../../utils/formatBytes'
import { Skeleton } from '../../components/Skeleton'
import './resource-usage-panel.css'

function formatGib(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`
}

function computeRows(quota: ProjectComputeQuota) {
  const ceiling = quota.platform_ceiling
  return [
    {
      label: 'Containers',
      used: quota.used_running_containers,
      limit: quota.max_running_containers ?? ceiling.running_containers,
      display: (value: number) => String(value),
    },
    {
      label: 'CPU',
      used: quota.used_cpu_millicores,
      limit: quota.max_cpu_millicores ?? ceiling.cpu_millicores,
      display: (value: number) => `${value} mCPU`,
    },
    {
      label: 'Memory',
      used: quota.used_memory_bytes,
      limit: quota.max_memory_bytes ?? ceiling.memory_bytes,
      display: formatGib,
    },
  ]
}

function fillWidth(used: number, limit: number): string {
  return `${limit === 0 ? 0 : Math.min(100, (used / limit) * 100)}%`
}

type ResourceUsagePanelProps = { refreshSignal?: number }

export function ResourceUsagePanel({ refreshSignal = 0 }: ResourceUsagePanelProps) {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [computeQuotas, setComputeQuotas] = useState<
    Record<string, ProjectComputeQuota>
  >({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getUsageSummary()
      .then(async (data) => {
        const entries = await Promise.all(
          data.projects.map(async (project) => {
            if (!project.project_id) {
              return null
            }
            try {
              return [
                project.project_id,
                await getProjectComputeQuota(project.project_id),
              ] as const
            } catch {
              return null
            }
          }),
        )
        if (cancelled) {
          return
        }
        const quotas: Record<string, ProjectComputeQuota> = {}
        for (const entry of entries) {
          if (entry) {
            quotas[entry[0]] = entry[1]
          }
        }
        setComputeQuotas(quotas)
        setSummary(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [refreshSignal])

  if (error) {
    return (
      <section className="dashboard-page__section">
        <p className="containers-banner containers-banner--err" role="alert">{error}</p>
      </section>
    )
  }

  if (!summary) {
    return (
      <section className="dashboard-page__section" aria-busy="true">
        <Skeleton className="skeleton--detail-title" />
      </section>
    )
  }

  const { projects } = summary
  if (projects.length === 0) {
    return (
      <section className="dashboard-page__section">
        <p className="resource-usage__empty">
          No running workloads to report usage for.
        </p>
      </section>
    )
  }

  return (
    <section className="dashboard-page__section">
      <h2 className="dashboard-page__subtitle">Resource usage by team</h2>
      <p className="resource-usage__summary">
        {summary.running_containers} running ·{' '}
        {formatBytes(summary.total_memory_usage_bytes)} memory ·{' '}
        {summary.total_cpu_percent.toFixed(1)}% CPU in total
      </p>
      <div className="resource-usage__grid">
        {projects.map((project, index) => {
          const quota = project.project_id
            ? computeQuotas[project.project_id]
            : undefined
          const rows = quota ? computeRows(quota) : []
          return (
            <div
              key={project.project_id ?? `personal-${index}`}
              className="resource-usage__card"
            >
              <h3 className="resource-usage__card-title">
                {project.team_name ?? project.project_name ?? 'Personal'}
              </h3>
              <p className="resource-usage__card-meta">
                {project.memory_usage_bytes_total
                  ? formatBytes(project.memory_usage_bytes_total)
                  : '0 B'}{' '}
                · {project.cpu_percent_total.toFixed(1)}% CPU
              </p>
              {project.storage_quota_bytes !== null ? (
                <p className="resource-usage__quota">
                  {formatGib(project.storage_used_bytes)} of{' '}
                  {formatGib(project.storage_quota_bytes)}
                  {project.storage_over_quota ? ' (over quota)' : ''}
                </p>
              ) : (
                <p className="resource-usage__quota">
                  {formatGib(project.storage_used_bytes)} used
                </p>
              )}
              {rows.some((row) => row.limit !== null) ? (
                <div className="resource-usage__compute">
                  {rows.map((row) =>
                    row.limit === null ? null : (
                      <div key={row.label} className="resource-usage__compute-row">
                        <span className="resource-usage__compute-label">
                          {row.label}
                        </span>
                        <span className="resource-usage__value">
                          {row.display(row.used)} / {row.display(row.limit)}
                        </span>
                        <div className="resource-usage__compute-bar">
                          <div
                            className={
                              row.used > row.limit
                                ? 'resource-usage__compute-bar-fill resource-usage__compute-bar-fill--over'
                                : 'resource-usage__compute-bar-fill'
                            }
                            style={{ width: fillWidth(row.used, row.limit) }}
                          />
                        </div>
                      </div>
                    ),
                  )}
                </div>
              ) : null}
              <ul className="resource-usage__list">
                {project.containers.map((container) => (
                  <li key={container.container_id} className="resource-usage__row">
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm resource-usage__name"
                      onClick={() =>
                        navigate(
                          `/containers/${container.container_id}/resources`,
                        )
                      }
                    >
                      {container.name}
                    </button>
                    <span className="resource-usage__value">
                      {container.memory_usage_bytes != null
                        ? formatBytes(container.memory_usage_bytes)
                        : 'stopped'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </section>
  )
}
