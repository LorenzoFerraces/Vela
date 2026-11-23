import { useEffect, useMemo, useState } from 'react'
import {
  exportShowbackCsv,
  formatApiError,
  getShowback,
  type ShowbackSummary,
} from '../api/client'
import { CHART_COLORS, MetricChart } from '../components/charts/MetricChart'
import { Skeleton } from '../components/Skeleton'
import './showback.css'

const formatValue = (value: number) =>
  value.toLocaleString('en-US', { maximumFractionDigits: 1 })

export default function ShowbackPage() {
  const [summary, setSummary] = useState<ShowbackSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getShowback()
      .then((data) => {
        if (active) setSummary(data)
      })
      .catch((err) => {
        if (active) setError(formatApiError(err))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const chartData = useMemo(
    () =>
      summary?.teams.map((team) => ({
        timestamp: team.team_name,
        cpuSeconds: team.cpu_seconds,
      })) ?? [],
    [summary]
  )

  const downloadCsv = async () => {
    if (!summary) return
    setExporting(true)
    setExportMessage(null)
    try {
      await exportShowbackCsv(summary.month)
      setExportMessage(`CSV downloaded for ${summary.month}.`)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setExporting(false)
    }
  }

  return (
    <section className="dashboard-page">
      <h1 className="dashboard-page__title">[ SHOWBACK ]</h1>

      {error ? (
        <div className="containers-banner containers-banner--err" role="alert">
          <p className="containers-banner__text">{error}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="showback__loading" aria-busy="true" aria-label="Loading showback">
          <Skeleton className="skeleton--team-row" />
          <Skeleton className="skeleton--metrics-chart" />
        </div>
      ) : !summary || summary.teams.length === 0 ? (
        <p className="containers-muted">No team usage data available for this month.</p>
      ) : (
        <>
          <div className="showback__toolbar">
            <span className="showback__month">{summary.month}</span>
            <button
              type="button"
              className="btn btn--sm btn--primary"
              onClick={() => void downloadCsv()}
              disabled={exporting}
            >
              {exporting ? 'Downloading…' : 'Download CSV'}
            </button>
          </div>

          {exportMessage ? (
            <p className="showback__status" role="status">
              {exportMessage}
            </p>
          ) : null}

          <div className="containers-table-wrap showback__table-wrap">
            <table className="containers-table showback__table">
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">CPU-seconds</th>
                  <th scope="col">Memory GiB-h</th>
                  <th scope="col">Storage GiB-days</th>
                </tr>
              </thead>
              <tbody>
                {summary.teams.map((team, index) => (
                  <tr key={`${team.team_name}-${index}`}>
                    <td>{team.team_name}</td>
                    <td>{formatValue(team.cpu_seconds)}</td>
                    <td>{formatValue(team.memory_gib_hours)}</td>
                    <td>{formatValue(team.storage_gib_days)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="showback__chart">
            <MetricChart
              data={chartData}
              dataKey="cpuSeconds"
              label="CPU-seconds"
              color={CHART_COLORS.accent}
              yAxisLabel="CPU-s"
              formatValue={formatValue}
              categoricalXAxis
            />
          </div>
        </>
      )}
    </section>
  )
}
