import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
  listIncomingInvitations,
  type IncomingProjectInvitation,
} from '../../api/client'

type Banner = { tone: 'ok' | 'err'; text: string } | null

export function TeamsInvitations() {
  const [incomingInvitations, setIncomingInvitations] = useState<
    IncomingProjectInvitation[]
  >([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<Banner>(null)
  const [busy, setBusy] = useState(false)

  const loadInvitations = useCallback(async () => {
    try {
      const incomingRows = await listIncomingInvitations()
      setIncomingInvitations(incomingRows)
      setLoading(false)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadInvitations()
  }, [loadInvitations])

  // This would be implemented in the parent component
  // const onAcceptInvitation = useCallback(async (invitationId: string) => {}, [])
  // const onRejectInvitation = useCallback(async (invitationId: string) => {}, [])

  return (
    <section className="teams-page__invites-banner">
      <h2 className="teams-page__invites-title">Incoming invitations</h2>
      <ul className="teams-page__invites-list">
        {incomingInvitations.map((invitation) => (
          <li key={invitation.id} className="teams-page__invites-row">
            <div>
              <strong>{invitation.project_name}</strong>
              <span className="teams-page__muted">
                {' '}
                from {invitation.inviter_email} as{' '}
                {formatRoleLabel(invitation.role)}
              </span>
            </div>
            {/* Accept/Reject buttons would be here */}
          </li>
        ))}
      </ul>
    </section>
  )
}

function formatRoleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}