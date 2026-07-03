import { useCallback, useEffect, useRef, useState } from 'react'
import type { ContainerStats } from '../../api/client'
import { formatApiError, getContainerStats } from '../../api/client'
import { formatBytes } from '../../utils/formatBytes'

type ContainerStatsPanelProps = {
  containerId: string
  isActive: boolean
}

export function ContainerStatsPanel({
  containerId,
  isActive,
}: ContainerStatsPanelProps) {
  const [stats, setStats] = useState<ContainerStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const fetchGenerationRef = useRef(0)

  const refreshStats = useCallback(async () => {
    const generation = ++fetchGenerationRef.current
    setLoading(true)
    try {
      const snapshot = await getContainerStats(containerId)
      if (generation !== fetchGenerationRef.current) {
        return
      }
      setStats(snapshot)
      setErrorText(null)
    } catch (error) {
      if (generation !== fetchGenerationRef.current) {
        return
      }
      setStats(null)
      setErrorText(formatApiError(error))
    } finally {
      if (generation === fetchGenerationRef.current) {
        setLoading(false)
      }
    }
  }, [containerId])

  useEffect(() => {
    if (!isActive) {
      return
    }
    void refreshStats()
  }, [isActive, containerId, refreshStats])

  return (
    <div className="workloads-stats-panel">
      <div className="workloads-stats-panel__toolbar">
        <span className="workloads-stats-panel__status" role="status">
          {loading ? 'Loading stats…' : 'Current snapshot'}
        </span>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void refreshStats()}
          disabled={loading}
        >
          Refresh
        </button>
      </div>
      {errorText ? (
        <p className="workloads-stats-panel__error" role="alert">
          {errorText}
        </p>
      ) : null}
      {stats ? (
        <dl className="workloads-stats-panel__grid">
          <div>
            <dt>CPU</dt>
            <dd>{stats.cpu_percent.toFixed(1)}%</dd>
          </div>
          <div>
            <dt>Memory</dt>
            <dd>
              {formatBytes(stats.memory_usage_bytes)}
              {stats.memory_limit_bytes > 0
                ? ` / ${formatBytes(stats.memory_limit_bytes)} (${stats.memory_percent.toFixed(1)}%)`
                : ''}
            </dd>
          </div>
          <div>
            <dt>Network in</dt>
            <dd>{formatBytes(stats.network_rx_bytes)}</dd>
          </div>
          <div>
            <dt>Network out</dt>
            <dd>{formatBytes(stats.network_tx_bytes)}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  )
}
