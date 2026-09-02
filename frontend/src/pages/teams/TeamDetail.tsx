import type { FormEvent } from 'react'
import type { Project, ProjectInvitation, ProjectMember } from '../../api/client'
import {
  TeamDetailSkeleton,
  TeamHintSectionSkeleton,
  TeamInviteSectionSkeleton,
} from '../../components/Skeleton'
import {
  formatRoleLabel,
  teamDescription,
  teamDisplayName,
} from '../../projects/teamDisplay'

type TeamDetailProps = {
  project: Project
  isSelectedOwner: boolean
  busy: boolean
  detailLoading: boolean
  members: ProjectMember[]
  pendingInvitations: ProjectInvitation[]
  inviteEmail: string
  inviteRole: 'viewer' | 'operator'
  onInviteEmailChange: (email: string) => void
  onInviteRoleChange: (role: 'viewer' | 'operator') => void
  onInvite: (event: FormEvent) => void
  onCancelInvitation: (invitation: ProjectInvitation) => void
  onChangeMemberRole: (userId: string, role: 'viewer' | 'operator') => void
  onRemoveMember: (userId: string, email: string) => void
  onLeaveTeam: () => void
}

export function TeamDetail({
  project,
  isSelectedOwner,
  busy,
  detailLoading,
  members,
  pendingInvitations,
  inviteEmail,
  inviteRole,
  onInviteEmailChange,
  onInviteRoleChange,
  onInvite,
  onCancelInvitation,
  onChangeMemberRole,
  onRemoveMember,
  onLeaveTeam,
}: TeamDetailProps) {
  return (
    <div className="teams-page__detail">
      <div className="teams-page__detail-header">
        <div>
          <h2 className="teams-page__detail-title">
            {teamDisplayName(project)}
          </h2>
          <p className="teams-page__muted">
            {teamDescription(project)}
          </p>
        </div>
        {project.role !== 'owner' ? (
          <button
            type="button"
            className="btn btn--ghost btn--sm teams-page__leave-btn"
            disabled={busy}
            onClick={onLeaveTeam}
          >
            Leave team
          </button>
        ) : null}
      </div>

      {detailLoading ? (
        <TeamDetailSkeleton>
          {isSelectedOwner ? (
            <TeamInviteSectionSkeleton />
          ) : (
            <TeamHintSectionSkeleton />
          )}
        </TeamDetailSkeleton>
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
                    {member.role === 'owner' ? (
                      <span className="teams-page__role-badge">Owner</span>
                    ) : isSelectedOwner ? (
                      <div className="teams-page__member-controls">
                        <select
                          className="teams-page__input teams-page__select--inline"
                          aria-label={`Role for ${member.email}`}
                          value={member.role}
                          disabled={busy}
                          onChange={(event) =>
                            onChangeMemberRole(
                              member.user_id,
                              event.target.value as 'viewer' | 'operator',
                            )
                          }
                        >
                          <option value="viewer">Viewer</option>
                          <option value="operator">Operator</option>
                        </select>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          disabled={busy}
                          onClick={() =>
                            onRemoveMember(member.user_id, member.email)
                          }
                        >
                          Remove
                        </button>
                      </div>
                    ) : (
                      <span className="teams-page__role-badge">
                        {formatRoleLabel(member.role)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {isSelectedOwner ? (
            <>
              <section className="teams-page__section">
                <h3 className="teams-page__section-title">Invite member</h3>
                <form className="teams-page__invite-form" onSubmit={onInvite}>
                  <label className="teams-page__field">
                    Email
                    <input
                      type="email"
                      className="teams-page__input"
                      autoComplete="off"
                      spellCheck={false}
                      value={inviteEmail}
                      disabled={busy}
                      onChange={(event) => onInviteEmailChange(event.target.value)}
                      placeholder="teammate@example.com…"
                      required
                    />
                  </label>
                  <label className="teams-page__field">
                    Role
                    <select
                      className="teams-page__input"
                      value={inviteRole}
                      disabled={busy}
                      onChange={(event) =>
                        onInviteRoleChange(
                          event.target.value as 'viewer' | 'operator',
                        )
                      }
                    >
                      <option value="viewer">Viewer</option>
                      <option value="operator">Operator</option>
                    </select>
                  </label>
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={busy}
                  >
                    Invite
                  </button>
                </form>
                <p className="teams-page__hint">
                  Invites must be accepted before the user gets access.
                </p>
              </section>

              {pendingInvitations.length > 0 ? (
                <section className="teams-page__section">
                  <h3 className="teams-page__section-title">
                    Pending invitations
                  </h3>
                  <ul className="teams-page__member-list">
                    {pendingInvitations.map((invitation) => (
                      <li
                        key={invitation.id}
                        className="teams-page__member-row"
                      >
                        <span>
                          {invitation.email} ·{' '}
                          {formatRoleLabel(invitation.role)}
                        </span>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          disabled={busy}
                          onClick={() => onCancelInvitation(invitation)}
                        >
                          Cancel
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          ) : (
            <p className="teams-page__muted">
              Your role: {formatRoleLabel(project.role)}. Only the
              owner can invite or manage members.
            </p>
          )}
        </>
      )}
    </div>
  )
}
