import type { ContainerInfo } from '../../api/client'

type ContainersWorkloadsSectionProps = {
  listLoading: boolean
  rows: ContainerInfo[]
  rowBusyId: string | null
  onStart: (containerId: string) => void
  onStop: (containerId: string) => void
  onRemove: (containerId: string) => void
}

export function ContainersWorkloadsSection({
  listLoading,
  rows,
  rowBusyId,
  onStart,
  onStop,
  onRemove,
}: ContainersWorkloadsSectionProps) {
  return (
    <div aria-live="polite" className="containers-page__workloads-live">
      {listLoading && rows.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="containers-muted">No Vela-managed containers yet.</p>
      ) : (
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Image</th>
                <th>Status</th>
                <th>Ports</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((containerRow) => (
                <tr key={containerRow.id}>
                  <td>{containerRow.name}</td>
                  <td className="containers-table__mono">{containerRow.image}</td>
                  <td>
                    <span className="containers-status">{containerRow.status}</span>
                  </td>
                  <td className="containers-table__ports">
                    {containerRow.ports.length === 0
                      ? '—'
                      : containerRow.ports
                          .map(
                            (portMapping) =>
                              `${portMapping.host_port}:${portMapping.container_port}/${portMapping.protocol}`,
                          )
                          .join(', ')}
                  </td>
                  <td className="containers-table__actions">
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      disabled={
                        rowBusyId === containerRow.id ||
                        containerRow.status === 'running'
                      }
                      onClick={() => void onStart(containerRow.id)}
                    >
                      Start
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      disabled={
                        rowBusyId === containerRow.id ||
                        containerRow.status !== 'running'
                      }
                      onClick={() => void onStop(containerRow.id)}
                    >
                      Stop
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--danger"
                      disabled={rowBusyId === containerRow.id}
                      onClick={() => void onRemove(containerRow.id)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
