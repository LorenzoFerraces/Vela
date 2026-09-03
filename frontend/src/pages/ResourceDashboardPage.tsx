import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  formatApiError,
  getMetricPoints,
  listContainers,
  type MetricPoint,
} from '../api/client'
import { MetricChart } from '../components/charts/MetricChart'
import { formatBytes } from '../utils/formatBytes'
import { Skeleton } from '../components/Skeleton'
import './resource-dashboard.css'

type TimeRange = '1h' | '6h' | '24h' | '7d'

const TIME_RANGE_HOURS: Record<TimeRange, number> = {
  '1h': 1,
  '6h': 6,
  '24h': 24,
  '7d': 168,
}

export default function ResourceDashboardPage() {
  const { containerId } = useParams<{ containerId: string }>()
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [metrics, setMetrics] = useState<MetricPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [containerName, setContainerName] = useState<string>('')

  const hours = TIME_RANGE_HOURS[timeRange]

  const requestSequence = useRef(0)

  const fetchMetrics = useCallback(async () => {
    if (!containerId) return
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setLoading(true)
    setError(null)
    try {
      const [points, containers] = await Promise.all([
        getMetricPoints(containerId, { hours }),
        listContainers(),
      ])
      if (requestSequence.current !== sequence) return
      setMetrics(points)
      setContainerName(containers.find((c) => c.id === containerId)?.name ?? '')
    } catch (err) {
      if (requestSequence.current !== sequence) return
      setError(formatApiError(err))
    } finally {
      if (requestSequence.current === sequence) setLoading(false)
    }
  }, [containerId, hours])

  useEffect(() => {
    void fetchMetrics()
  }, [fetchMetrics])

  const chartData = useMemo(() => {
    return metrics.map((m) => ({
      timestamp: m.timestamp,
      cpu: m.cpu_percent,
      memoryUsage: m.memory_usage_bytes,
      memoryLimit: m.memory_limit_bytes,
      memoryPercent: m.memory_percent,
      networkRx: m.network_rx_bytes,
      networkTx: m.network_tx_bytes,
    }))
  }, [metrics])

  const timeRangeButtons: TimeRange[] = ['1h', '6h', '24h', '7d']

  return (
    <section className="dashboard-page">
      <h1 className="dashboard-page__title">
        Resource Dashboard
        {containerName ? ` — ${containerName}` : ''}
      </h1>

      <div className="metrics-toolbar">
        <span className="metrics-toolbar__label">Time range:</span>
        {timeRangeButtons.map((range) => (
          <button
            key={range}
            type="button"
            className={`btn btn--sm ${timeRange === range ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => setTimeRange(range)}
          >
            {range}
          </button>
        ))}
        <button
          type="button"
          className="btn btn--ghost btn--sm metrics-toolbar__refresh"
          onClick={() => void fetchMetrics()}
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="containers-banner containers-banner--err" role="alert">
          <p className="containers-banner__text">{error}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="metrics-grid">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="skeleton--metrics-chart" />
          ))}
        </div>
      ) : metrics.length === 0 ? (
        <div className="metrics-empty">
          <p>No metrics data available yet.</p>
          <p className="metrics-empty__hint">
            The background collector records stats every 30 seconds. Data will appear here shortly.
          </p>
        </div>
      ) : (
        <div className="metrics-grid">
          <div className="metrics-card">
            <h3 className="metrics-card__title">CPU Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="cpu"
              label="CPU %"
              color="#bc7fed"
              yAxisLabel="CPU %"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card">
            <h3 className="metrics-card__title">Memory Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryUsage"
              label="Memory"
              color="#4ade80"
              yAxisLabel="Memory"
              chartType="area"
              formatValue={formatBytes}
              referenceLine={
                chartData.length > 0
                  ? { value: chartData[0].memoryLimit, label: 'Limit' }
                  : undefined
              }
            />
          </div>

          <div className="metrics-card">
            <h3 className="metrics-card__title">Memory Percent</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryPercent"
              label="Memory %"
              color="#fbbf24"
              yAxisLabel="Mem %"
              chartType="area"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card">
            <h3 className="metrics-card__title">Network I/O</h3>
            <MetricChart
              data={chartData}
              label="Network I/O"
              yAxisLabel="Bytes"
              formatValue={formatBytes}
              series={[
                { dataKey: 'networkRx', label: 'Network Rx', color: '#9aa5b4' },
                { dataKey: 'networkTx', label: 'Network Tx', color: '#bc7fed' },
              ]}
            />
          </div>
        </div>
      )}
    </section>
  )
}
