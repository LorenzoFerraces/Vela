import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  formatApiError,
  listProjectMembers,
  type Project,
  type ProjectMember,
} from '../../api/client'
import { teamDescription, teamDisplayName } from '../../projects/teamDisplay'

type Banner = { tone: 'ok' | 'err'; text: string } | null

function formatRoleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

export function TeamsDetail() {
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)
  const detailRequestRef = useRef(0)

  const loadTeamDetail = useCallback(async (project: Project) => {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    setDetailLoading(true)
    try {
      const memberRows = await listProjectMembers(project.id)
      if (detailRequestRef.current !== requestId) {
        return
      }
      setMembers(memberRows)
    } catch (error) {
      if (detailRequestRef.current !== requestId) {
        return
      }
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      if (detailRequestRef.current === requestId) {
        setDetailLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    if (!routeProjectId) {
      return
    }
    // Note: This would need to get the project data from a parent component
    // For now, we'll leave this as a placeholder
  }, [routeProjectId])

  return (
    <div className="teams-page__detail">
      <div className="teams-page__detail-header">
        <div>
          <h2 className="teams-page__detail-title">
            {/* This would be dynamically set from project data */}
            Team Name
          </h2>
          <p className="teams-page__muted">
            {/* This would be dynamically set from project data */}
            Team description
          </p>
        </div>
        {/* Leave team button would be here */}
      </div>

      {detailLoading ? (
        <TeamDetailSkeleton showInviteSection={false} />
      ) : (
        <>
          <section className="teams-page__section">
            <h3 className="teams-page__section-title">Members</h3>
            {members.length === 0 ? (
              <p className="teams-page__muted">No members yet.</p>
            ) : (
              <ul className="teams-page__member-list">
                {members.map((member) => (
                  <li key={member.user_id} className="teams-page__member-row">
                    <span className="teams-page__member-email">
                      {member.email}
                    </span>
                    <span className="teams-page__role-badge">
                      {formatRoleLabel(member.role)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}