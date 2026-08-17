import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  formatApiError,
  getUsageSummary,
  type UsageSummary,
} from '../../api/client'
import { formatBytes } from '../../utils/formatBytes'
import { Skeleton } from '../../components/Skeleton'

export function ResourceUsagePanel() {
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
  }, [])

  if (error) {
    return (
      <section className="dashboard-page__section">
        <p className="containers-banner containers-banner--err">{error}</p>
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
        <p style={{ color: '#6b7280', fontSize: 14 }}>
          No running workloads to report usage for.
        </p>
      </section>
    )
  }

  return (
    <section className="dashboard-page__section">
      <h2 className="dashboard-page__subtitle">Resource usage by team</h2>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 12 }}>
        {summary.running_containers} running ·{' '}
        {formatBytes(summary.total_memory_usage_bytes)} memory ·{' '}
        {summary.total_cpu_percent.toFixed(1)}% CPU in total
      </p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 12,
        }}
      >
        {projects.map((project, index) => (
          <div
            key={project.project_id ?? `personal-${index}`}
            style={{
              border: '1px solid #e5e7eb',
              borderRadius: 8,
              padding: 16,
            }}
          >
            <h3 style={{ margin: 0, fontSize: 14, color: '#374151' }}>
              {project.team_name ?? project.project_name ?? 'Personal'}
            </h3>
            <p style={{ margin: '4px 0 12px', fontSize: 13, color: '#6b7280' }}>
              {project.memory_usage_bytes_total
                ? formatBytes(project.memory_usage_bytes_total)
                : '0 B'}{' '}
              · {project.cpu_percent_total.toFixed(1)}% CPU
            </p>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {project.containers.map((container) => (
                <li
                  key={container.container_id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 13,
                    padding: '2px 0',
                  }}
                >
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    style={{ color: '#3b82f6' }}
                    onClick={() =>
                      navigate(
                        `/containers/${container.container_id}/resources`,
                      )
                    }
                  >
                    {container.name}
                  </button>
                  <span style={{ color: '#6b7280' }}>
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
