import { Skeleton } from '../Skeleton'
import type { DeployJob } from '../../api/client'

const PHASE_LABELS: Record<string, string> = {
  queued: 'QUEUED',
  preparing: 'PREPARING',
  building: 'BUILDING',
  starting: 'STARTING',
  routing: 'ROUTING',
  deploying: 'DEPLOYING',
  rolling_back: 'ROLLING BACK',
}

export function DeployJobRow({ job }: { job: DeployJob }) {
  const phaseLabel = PHASE_LABELS[job.phase] ?? job.phase.toUpperCase()
  return (
    <tr className="deploy-job-row" aria-busy="true">
      <td className="workloads-table__name-cell">{job.name}</td>
      <td className="containers-table__mono">
        {job.source_label || job.phase_detail || '—'}
      </td>
      <td>
        <span className="deploy-job-row__status" role="status">
          <span className="deploy-job-row__dot" aria-hidden="true" />
          <span className="deploy-job-row__phase">{phaseLabel}</span>
        </span>
      </td>
      <td className="containers-table__ports">
        <Skeleton className="deploy-job-row__skeleton" />
      </td>
      <td className="workloads-table__url-cell">
        <Skeleton className="deploy-job-row__skeleton" />
      </td>
      <td>
        <span className="containers-muted">—</span>
      </td>
      <td className="containers-table__actions" />
      <td className="workloads-table__expand-cell" />
    </tr>
  )
}
