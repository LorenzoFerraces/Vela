import { useCallback, useState } from 'react'
import {
  formatApiError,
  removeContainer,
  startContainer,
  stopContainer,
} from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import { DashboardWorkloadsTable } from '../components/workloads/WorkloadsTable'
import { useWorkloadGroups } from './containers/useWorkloadGroups'
import { DeploymentHistorySection } from './containers/DeploymentHistorySection'

export default function DashboardPage() {
  const [banner, setBanner] = useState<{ tone: 'err'; text: string } | null>(
    null,
  )
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null)
  const [historyRefreshSignal, setHistoryRefreshSignal] = useState(0)

  const reportListLoadError = useCallback((detail: string) => {
    setBanner({ tone: 'err', text: detail })
  }, [])

  const { groups, listLoading, refresh } = useWorkloadGroups(reportListLoadError)

  const onStart = useCallback(
    async (containerId: string) => {
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
    },
    [refresh],
  )

  const onStop = useCallback(
    async (containerId: string) => {
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
    },
    [refresh],
  )

  const onRemove = useCallback(
    (containerId: string) => setPendingRemoveId(containerId),
    [],
  )

  async function onConfirmRemove() {
    if (pendingRemoveId === null) return
    const containerId = pendingRemoveId
    setRowBusy(containerId)
    setBanner(null)
    try {
      await removeContainer(containerId, true)
      await refresh()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setRowBusy(null)
      setPendingRemoveId(null)
    }
  }

  return (
    <section className="dashboard-page">
      <h1 className="dashboard-page__title">Dashboard</h1>
      <p className="dashboard-page__lead">
        Monitor workloads: logs, resource stats per instance, and grouped
        replicas for auto-scaled deployments. Containers that are stopped,
        restarting, or failing health checks are listed first.
      </p>

      {banner ? (
        <div
          className="containers-banner containers-banner--err"
          role="alert"
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      <h2 className="dashboard-page__subtitle">Running workloads</h2>
      <DashboardWorkloadsTable
        listLoading={listLoading}
        groups={groups}
        rowBusyId={rowBusy}
        onStart={onStart}
        onStop={onStop}
        onRemove={onRemove}
      />

      <DeploymentHistorySection refreshSignal={historyRefreshSignal} />

      <div className="dashboard-page__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setBanner(null)
            void refresh()
            setHistoryRefreshSignal((signal) => signal + 1)
          }}
          disabled={listLoading}
        >
          Refresh
        </button>
      </div>

      <ConfirmDialog
        open={pendingRemoveId !== null}
        title="Remove container?"
        message={`${pendingRemoveId ?? ''} will be removed.`}
        confirmLabel={rowBusy === pendingRemoveId ? 'Removing…' : 'Remove'}
        busy={rowBusy === pendingRemoveId}
        onConfirm={() => void onConfirmRemove()}
        onClose={() => setPendingRemoveId(null)}
      />
    </section>
  )
}
