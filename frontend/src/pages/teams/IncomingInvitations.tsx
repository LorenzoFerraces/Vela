import type { IncomingProjectInvitation } from '../../api/client'
import { formatRoleLabel } from '../../projects/teamDisplay'

type IncomingInvitationsProps = {
  invitations: IncomingProjectInvitation[]
  busy: boolean
  onAccept: (invitationId: string) => void
  onReject: (invitationId: string) => void
}

export function IncomingInvitations({
  invitations,
  busy,
  onAccept,
  onReject,
}: IncomingInvitationsProps) {
  if (invitations.length === 0) {
    return null
  }

  return (
    <section className="teams-page__invites-banner">
      <h2 className="teams-page__invites-title">Incoming invitations</h2>
      <ul className="teams-page__invites-list">
        {invitations.map((invitation) => (
          <li key={invitation.id} className="teams-page__invites-row">
            <div>
              <strong>{invitation.project_name}</strong>
              <span className="teams-page__muted">
                {' '}
                from {invitation.inviter_email} as{' '}
                {formatRoleLabel(invitation.role)}
              </span>
            </div>
            <div className="teams-page__row-actions">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={busy}
                onClick={() => onAccept(invitation.id)}
              >
                Accept
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={busy}
                onClick={() => onReject(invitation.id)}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
