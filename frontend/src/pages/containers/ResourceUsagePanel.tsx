import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  formatApiError,
  getUsageSummary,
  type UsageSummary,
} from '../../api/client'
import { formatBytes } from '../../utils/formatBytes'
import { Skeleton } from '../../components/Skeleton'
import './resource-usage-panel.css'

function formatGib(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`
}

type ResourceUsagePanelProps = { refreshSignal?: number }

export function ResourceUsagePanel({ refreshSignal = 0 }: ResourceUsagePanelProps) {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data)
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
        {projects.map((project, index) => (
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
        ))}
      </div>
    </section>
  )
}
