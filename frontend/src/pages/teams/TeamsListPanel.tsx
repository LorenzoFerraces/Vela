import { Link } from 'react-router-dom'
import type { Project } from '../../api/client'
import { formatRoleLabel, teamDisplayName } from '../../projects/teamDisplay'

type TeamsListPanelProps = {
  projects: Project[]
  selectedProjectId: string | null
}

export function TeamsListPanel({
  projects,
  selectedProjectId,
}: TeamsListPanelProps) {
  return (
    <aside className="teams-page__sidebar">
      <h2 className="teams-page__sidebar-title">Your teams</h2>
      <ul className="teams-page__team-list">
        {projects.map((project) => {
          const isActive = selectedProjectId === project.id
          return (
            <li key={project.id}>
              <Link
                to={`/teams/${project.id}`}
                aria-current={isActive ? 'page' : undefined}
                className={
                  isActive
                    ? 'teams-page__team-link teams-page__team-link--active'
                    : 'teams-page__team-link'
                }
              >
                <span className="teams-page__team-name">
                  {teamDisplayName(project)}
                </span>
                <span className="teams-page__team-role">
                  {formatRoleLabel(project.role)}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
