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

      <div className="metrics-toolbar" style={{ display: 'flex', gap: '8px', marginBottom: '16px', alignItems: 'center' }}>
        <span style={{ fontSize: '14px', color: '#6b7280' }}>Time range:</span>
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
          className="btn btn--ghost btn--sm"
          onClick={() => void fetchMetrics()}
          disabled={loading}
          style={{ marginLeft: 'auto' }}
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="skeleton--metrics-chart" />
          ))}
        </div>
      ) : metrics.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: '#6b7280' }}>
          <p>No metrics data available yet.</p>
          <p style={{ fontSize: '14px' }}>
            The background collector records stats every 30 seconds. Data will appear here shortly.
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>CPU Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="cpu"
              label="CPU %"
              color="#3b82f6"
              yAxisLabel="CPU %"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Memory Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryUsage"
              label="Memory"
              color="#10b981"
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

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Memory Percent</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryPercent"
              label="Memory %"
              color="#f59e0b"
              yAxisLabel="Mem %"
              chartType="area"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Network I/O</h3>
            <MetricChart
              data={chartData}
              dataKey="networkRx"
              label="Network Rx"
              color="#8b5cf6"
              yAxisLabel="Bytes"
              formatValue={formatBytes}
            />
          </div>
        </div>
      )}
    </section>
  )
}
