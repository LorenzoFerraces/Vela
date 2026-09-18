import ConfirmDialog from '../components/ConfirmDialog'
import { TeamsPageSkeleton } from '../components/Skeleton'
import { IncomingInvitations } from './teams/IncomingInvitations'
import { TeamDetail } from './teams/TeamDetail'
import { TeamsListPanel } from './teams/TeamsListPanel'
import { useTeamManagement } from './teams/useTeamManagement'

export default function TeamsPage() {
  const {
    selectedProject,
    isSelectedOwner,
    loading,
    detailLoading,
    busy,
    banner,
    showCreateForm,
    setShowCreateForm,
    newTeamName,
    setNewTeamName,
    onCreateTeam,
    incomingInvitations,
    onAcceptInvitation,
    onRejectInvitation,
    projects,
    storageQuota,
    quotaError,
    quotaInput,
    setQuotaInput,
    onSaveQuota,
    members,
    pendingInvitations,
    inviteEmail,
    inviteRole,
    setInviteEmail,
    setInviteRole,
    onInvite,
    setCancelInvitationTarget,
    onChangeMemberRole,
    onRemoveMember,
    onLeaveTeam,
    cancelInvitationTarget,
    onCancelInvitation,
    pendingAction,
    setPendingAction,
    onConfirmRemoveMember,
    onConfirmLeaveTeam,
  } = useTeamManagement()

  return (
    <section className="teams-page">
      <header className="teams-page__header">
        <div>
          <h1 className="teams-page__title">Teams</h1>
          <p className="teams-page__lead">
            Share container workloads with teammates. Each team has its own members
            and roles.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          disabled={busy}
          onClick={() => setShowCreateForm((open) => !open)}
        >
          {showCreateForm ? 'Cancel' : 'Create team'}
        </button>
      </header>

      {banner ? (
        <p
          className={
            banner.tone === 'ok'
              ? 'settings-banner settings-banner--ok'
              : 'settings-banner settings-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : 'status'}
        >
          {banner.text}
        </p>
      ) : null}

      {showCreateForm ? (
        <form className="teams-page__create" onSubmit={onCreateTeam}>
          <label className="teams-page__field teams-page__field--grow">
            Team name
            <input
              type="text"
              className="teams-page__input"
              value={newTeamName}
              disabled={busy}
              onChange={(event) => setNewTeamName(event.target.value)}
              placeholder="My team…"
              maxLength={255}
              required
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            Create
          </button>
        </form>
      ) : null}

      <IncomingInvitations
        invitations={incomingInvitations}
        busy={busy}
        onAccept={onAcceptInvitation}
        onReject={onRejectInvitation}
      />

      {loading ? (
        <TeamsPageSkeleton />
      ) : projects.length === 0 ? (
        <p className="teams-page__muted">No teams yet. Create one to get started.</p>
      ) : (
        <div className="teams-page__layout">
          <TeamsListPanel
            projects={projects}
            selectedProjectId={selectedProject?.id ?? null}
          />

          {selectedProject ? (
            <TeamDetail
              project={selectedProject}
              isSelectedOwner={isSelectedOwner}
              busy={busy}
              detailLoading={detailLoading}
              storageQuota={storageQuota}
              quotaError={quotaError}
              quotaInput={quotaInput}
              onQuotaInputChange={setQuotaInput}
              onSaveQuota={onSaveQuota}
              members={members}
              pendingInvitations={pendingInvitations}
              inviteEmail={inviteEmail}
              inviteRole={inviteRole}
              onInviteEmailChange={setInviteEmail}
              onInviteRoleChange={setInviteRole}
              onInvite={onInvite}
              onCancelInvitation={setCancelInvitationTarget}
              onChangeMemberRole={onChangeMemberRole}
              onRemoveMember={onRemoveMember}
              onLeaveTeam={onLeaveTeam}
            />
          ) : null}
        </div>
      )}

      <ConfirmDialog
        open={cancelInvitationTarget !== null}
        title="Cancel invitation?"
        message={
          cancelInvitationTarget
            ? `The invitation for ${cancelInvitationTarget.email} will be revoked.`
            : ''
        }
        confirmLabel={busy ? 'Cancelling…' : 'Cancel invite'}
        busy={busy}
        onConfirm={() => {
          if (cancelInvitationTarget) {
            void onCancelInvitation(cancelInvitationTarget.id)
          }
        }}
        onClose={() => setCancelInvitationTarget(null)}
      />

      <ConfirmDialog
        open={pendingAction !== null}
        title={
          pendingAction?.kind === 'leave-team'
            ? `Leave “${pendingAction.teamLabel}”?`
            : 'Remove member?'
        }
        message={
          pendingAction?.kind === 'leave-team'
            ? 'You will lose access to its workloads.'
            : pendingAction
              ? `${pendingAction.email} will be removed from this team.`
              : ''
        }
        confirmLabel={
          pendingAction?.kind === 'leave-team'
            ? busy
              ? 'Leaving…'
              : 'Leave'
            : busy
              ? 'Removing…'
              : 'Remove'
        }
        busy={busy && pendingAction !== null}
        onConfirm={() => {
          if (pendingAction?.kind === 'leave-team') {
            void onConfirmLeaveTeam()
          } else if (pendingAction) {
            void onConfirmRemoveMember()
          }
        }}
        onClose={() => setPendingAction(null)}
      />
    </section>
  )
}
