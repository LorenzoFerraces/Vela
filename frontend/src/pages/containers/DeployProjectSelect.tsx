import type { Project } from '../../api/client'
import { teamDisplayName } from '../../projects/teamDisplay'

type DeployProjectSelectProps = {
  projects: Project[]
  selectedProjectId: string
  onSelectedProjectIdChange: (projectId: string) => void
  loading: boolean
  error: string | null
}

export function DeployProjectSelect({
  projects,
  selectedProjectId,
  onSelectedProjectIdChange,
  loading,
  error,
}: DeployProjectSelectProps) {
  if (loading) {
    return (
      <p className="containers-muted containers-form__hint" role="status">
        Loading teams…
      </p>
    )
  }

  if (error) {
    return (
      <p className="containers-source-check containers-source-check--err" role="alert">
        {error}
      </p>
    )
  }

  if (projects.length === 0) {
    return (
      <p className="containers-source-check containers-source-check--warn" role="status">
        You need owner or operator access on a team to deploy containers.
      </p>
    )
  }

  return (
    <>
      <label className="containers-form__label" htmlFor="deploy-project-select">
        Team / workspace
      </label>
      <select
        id="deploy-project-select"
        className="containers-form__input containers-form__select"
        value={selectedProjectId}
        onChange={(event) => onSelectedProjectIdChange(event.target.value)}
      >
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {teamDisplayName(project)}
          </option>
        ))}
      </select>
    </>
  )
}
