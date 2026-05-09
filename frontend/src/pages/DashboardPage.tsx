import { useCallback, useState } from 'react'
import {
  formatApiError,
  removeContainer,
  startContainer,
  stopContainer,
} from '../api/client'
import { WorkloadsTable } from '../components/workloads/WorkloadsTable'
import { useContainerList } from './containers/useContainerList'

export default function DashboardPage() {
  const [banner, setBanner] = useState<{ tone: 'err'; text: string } | null>(
    null,
  )
  const [rowBusy, setRowBusy] = useState<string | null>(null)

  const reportListLoadError = useCallback((detail: string) => {
    setBanner({ tone: 'err', text: detail })
  }, [])

  const { rows, listLoading, refresh } = useContainerList(reportListLoadError)

  async function onStart(containerId: string) {
    setRowBusy(containerId)
    setBanner(null)
    try {
      await startContainer(containerId)
      await refresh()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onStop(containerId: string) {
    setRowBusy(containerId)
    setBanner(null)
    try {
      await stopContainer(containerId)
      await refresh()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  async function onRemove(containerId: string) {
    if (!window.confirm('Remove this container?')) return
    setRowBusy(containerId)
    setBanner(null)
    try {
      await removeContainer(containerId, true)
      await refresh()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
    }
  }

  return (
    <section className="dashboard-page">
      <h1 className="dashboard-page__title">Dashboard</h1>
      <p className="dashboard-page__lead">
        Monitor workloads: logs stream live over WebSocket. Containers that are
        stopped, restarting, or failing health checks are listed first.
      </p>

      {banner ? (
        <div
          className="containers-banner containers-banner--err"
          role="alert"
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      <div className="dashboard-page__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setBanner(null)
            void refresh()
          }}
          disabled={listLoading}
        >
          Refresh
        </button>
      </div>

      <h2 className="dashboard-page__subtitle">Running workloads</h2>
      <WorkloadsTable
        listLoading={listLoading}
        rows={rows}
        rowBusyId={rowBusy}
        onStart={onStart}
        onStop={onStop}
        onRemove={onRemove}
        prioritizeProblemWorkloads
      />
    </section>
  )
}
