import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  acceptProjectInvitation,
  cancelProjectInvitation,
  createProject,
  createProjectInvitation,
  formatApiError,
  leaveProject,
  listIncomingInvitations,
  listProjectInvitations,
  listProjectMembers,
  listProjects,
  type IncomingProjectInvitation,
  type Project,
  type ProjectInvitation,
  type ProjectMember,
  rejectProjectInvitation,
  removeProjectMember,
  updateProjectMemberRole,
} from '../api/client'
import { TeamDetailSkeleton, TeamsPageSkeleton } from '../components/Skeleton'

type Banner = { tone: 'ok' | 'err'; text: string } | null

function formatRoleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

function teamDisplayName(project: Project): string {
  if (project.is_personal && project.role === 'owner') {
    return 'Personal workspace'
  }
  if (project.is_personal) {
    return `${project.owner_email}'s workspace`
  }
  return project.name
}

function teamDescription(project: Project): string {
  if (project.is_personal && project.role === 'owner') {
    return 'Your private workspace. Invite others to share your containers.'
  }
  if (project.is_personal) {
    return `Shared workspace owned by ${project.owner_email}.`
  }
  return 'Shared team workspace for containers and deployments.'
}

export default function TeamsPage() {
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [incomingInvitations, setIncomingInvitations] = useState<
    IncomingProjectInvitation[]
  >([])
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [pendingInvitations, setPendingInvitations] = useState<ProjectInvitation[]>(
    []
  )
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newTeamName, setNewTeamName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'viewer' | 'operator'>('viewer')

  const selectedProject = useMemo(() => {
    if (projects.length === 0) {
      return null
    }
    if (routeProjectId) {
      return projects.find((project) => project.id === routeProjectId) ?? projects[0]
    }
    return projects[0]
  }, [projects, routeProjectId])

  const isSelectedOwner = selectedProject?.role === 'owner'

  const loadProjects = useCallback(async () => {
    const [projectRows, incomingRows] = await Promise.all([
      listProjects(),
      listIncomingInvitations(),
    ])
    setProjects(projectRows)
    setIncomingInvitations(incomingRows)
    return projectRows
  }, [])

  const loadTeamDetail = useCallback(async (project: Project) => {
    setDetailLoading(true)
    try {
      const memberRows = await listProjectMembers(project.id)
      setMembers(memberRows)
      if (project.role === 'owner') {
        const invitationRows = await listProjectInvitations(project.id)
        setPendingInvitations(invitationRows)
      } else {
        setPendingInvitations([])
      }
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const refreshProjectsList = useCallback(async () => {
    try {
      await loadProjects()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    }
  }, [loadProjects])

  const refreshSelectedTeamDetail = useCallback(async () => {
    if (!routeProjectId) {
      return
    }
    const project = projects.find((item) => item.id === routeProjectId)
    if (!project) {
      return
    }
    await loadTeamDetail(project)
  }, [routeProjectId, projects, loadTeamDetail])

  useEffect(() => {
    let cancelled = false

    async function initialLoad() {
      setLoading(true)
      try {
        await loadProjects()
        if (!cancelled) {
          setBanner(null)
        }
      } catch (error) {
        if (!cancelled) {
          setBanner({ tone: 'err', text: formatApiError(error) })
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void initialLoad()
    return () => {
      cancelled = true
    }
  }, [loadProjects])

  useEffect(() => {
    if (loading || !routeProjectId) {
      return
    }
    const project = projects.find((item) => item.id === routeProjectId)
    if (!project) {
      return
    }
    void loadTeamDetail(project)
  }, [loading, routeProjectId, projects, loadTeamDetail])

  useEffect(() => {
    if (loading || projects.length === 0) {
      return
    }
    if (!routeProjectId) {
      navigate(`/teams/${projects[0].id}`, { replace: true })
      return
    }
    const exists = projects.some((project) => project.id === routeProjectId)
    if (!exists) {
      navigate(`/teams/${projects[0].id}`, { replace: true })
    }
  }, [loading, projects, routeProjectId, navigate])

  async function onCreateTeam(event: React.FormEvent) {
    event.preventDefault()
    const trimmedName = newTeamName.trim()
    if (!trimmedName) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      const created = await createProject(trimmedName)
      setNewTeamName('')
      setShowCreateForm(false)
      setBanner({ tone: 'ok', text: `Team "${created.name}" created.` })
      setProjects((current) => [...current, created])
      navigate(`/teams/${created.id}`)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onInvite(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedProject || !isSelectedOwner) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await createProjectInvitation(selectedProject.id, {
        email: inviteEmail.trim(),
        role: inviteRole,
      })
      setInviteEmail('')
      setBanner({
        tone: 'ok',
        text: 'Invitation sent — they must accept it on the Teams page.',
      })
      await refreshSelectedTeamDetail()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onAcceptInvitation(invitationId: string) {
    setBusy(true)
    setBanner(null)
    try {
      const joined = await acceptProjectInvitation(invitationId)
      setBanner({ tone: 'ok', text: `You joined ${joined.name}.` })
      await refreshProjectsList()
      navigate(`/teams/${joined.id}`)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onRejectInvitation(invitationId: string) {
    setBusy(true)
    setBanner(null)
    try {
      await rejectProjectInvitation(invitationId)
      await refreshProjectsList()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onCancelInvitation(invitationId: string) {
    if (!selectedProject) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await cancelProjectInvitation(selectedProject.id, invitationId)
      await refreshSelectedTeamDetail()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onChangeMemberRole(userId: string, role: 'viewer' | 'operator') {
    if (!selectedProject) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await updateProjectMemberRole(selectedProject.id, userId, role)
      await refreshSelectedTeamDetail()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onRemoveMember(userId: string, email: string) {
    if (!selectedProject) {
      return
    }
    if (!window.confirm(`Remove ${email} from this team?`)) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await removeProjectMember(selectedProject.id, userId)
      await refreshSelectedTeamDetail()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function onLeaveTeam() {
    if (!selectedProject || selectedProject.role === 'owner') {
      return
    }
    const teamLabel = teamDisplayName(selectedProject)
    if (
      !window.confirm(
        `Leave "${teamLabel}"? You will lose access to its workloads.`,
      )
    ) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await leaveProject(selectedProject.id)
      setBanner({ tone: 'ok', text: 'You left the team.' })
      const projectRows = await listProjects()
      setProjects(projectRows)
      const next = projectRows[0]
      if (next) {
        navigate(`/teams/${next.id}`)
      } else {
        navigate('/teams', { replace: true })
      }
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

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
          role={banner.tone === 'err' ? 'alert' : undefined}
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
              placeholder="My team"
              maxLength={255}
              required
              autoFocus
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            Create
          </button>
        </form>
      ) : null}

      {incomingInvitations.length > 0 ? (
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
                <div className="teams-page__row-actions">
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    disabled={busy}
                    onClick={() => void onAcceptInvitation(invitation.id)}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    disabled={busy}
                    onClick={() => void onRejectInvitation(invitation.id)}
                  >
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {loading ? (
        <TeamsPageSkeleton />
      ) : projects.length === 0 ? (
        <p className="teams-page__muted">No teams yet. Create one to get started.</p>
      ) : (
        <div className="teams-page__layout">
          <aside className="teams-page__sidebar">
            <h2 className="teams-page__sidebar-title">Your teams</h2>
            <ul className="teams-page__team-list">
              {projects.map((project) => {
                const isActive = selectedProject?.id === project.id
                return (
                  <li key={project.id}>
                    <Link
                      to={`/teams/${project.id}`}
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

          {selectedProject ? (
            <div className="teams-page__detail">
              <div className="teams-page__detail-header">
                <div>
                  <h2 className="teams-page__detail-title">
                    {teamDisplayName(selectedProject)}
                  </h2>
                  <p className="teams-page__muted">
                    {teamDescription(selectedProject)}
                  </p>
                </div>
                {selectedProject.role !== 'owner' ? (
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm teams-page__leave-btn"
                    disabled={busy}
                    onClick={() => void onLeaveTeam()}
                  >
                    Leave team
                  </button>
                ) : null}
              </div>

              {detailLoading ? (
                <TeamDetailSkeleton showInviteSection={isSelectedOwner} />
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
                                  className="teams-page__input teams-page__select teams-page__select--inline"
                                  value={member.role}
                                  disabled={busy}
                                  onChange={(event) =>
                                    void onChangeMemberRole(
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
                                    void onRemoveMember(
                                      member.user_id,
                                      member.email,
                                    )
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
                              value={inviteEmail}
                              disabled={busy}
                              onChange={(event) => setInviteEmail(event.target.value)}
                              placeholder="teammate@example.com"
                              required
                            />
                          </label>
                          <label className="teams-page__field">
                            Role
                            <select
                              className="teams-page__input teams-page__select"
                              value={inviteRole}
                              disabled={busy}
                              onChange={(event) =>
                                setInviteRole(
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
                                  onClick={() =>
                                    void onCancelInvitation(invitation.id)
                                  }
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
                      Your role: {formatRoleLabel(selectedProject.role)}. Only the
                      owner can invite or manage members.
                    </p>
                  )}
                </>
              )}
            </div>
          ) : null}
        </div>
      )}
    </section>
  )
}
