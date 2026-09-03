import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  acceptProjectInvitation,
  cancelProjectInvitation,
  createProject,
  createProjectInvitation,
  formatApiError,
  getProjectStorageQuota,
  leaveProject,
  listIncomingInvitations,
  listProjectInvitations,
  listProjectMembers,
  listProjects,
  type IncomingProjectInvitation,
  type Project,
  type ProjectInvitation,
  type ProjectMember,
  type ProjectStorageQuota,
  rejectProjectInvitation,
  removeProjectMember,
  updateProjectMemberRole,
  updateProjectStorageQuota,
} from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import { TeamsPageSkeleton } from '../components/Skeleton'
import { teamDisplayName } from '../projects/teamDisplay'
import { IncomingInvitations } from './teams/IncomingInvitations'
import { TeamDetail } from './teams/TeamDetail'
import { TeamsListPanel } from './teams/TeamsListPanel'

type Banner = { tone: 'ok' | 'err'; text: string } | null

export default function TeamsPage() {
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [incomingInvitations, setIncomingInvitations] = useState<
    IncomingProjectInvitation[]
  >([])
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [storageQuota, setStorageQuota] = useState<ProjectStorageQuota | null>(
    null,
  )
  const [quotaInput, setQuotaInput] = useState('')
  const [quotaError, setQuotaError] = useState<string | null>(null)
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
  const [cancelInvitationTarget, setCancelInvitationTarget] = useState<
    ProjectInvitation | null
  >(null)
  const [pendingAction, setPendingAction] = useState<
    | { kind: 'remove-member'; userId: string; email: string }
    | { kind: 'leave-team'; teamLabel: string }
    | null
  >(null)
  const detailRequestRef = useRef(0)
  const detailLoadedForRef = useRef<string | null>(null)

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
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    setDetailLoading(true)
    setQuotaError(null)
    void getProjectStorageQuota(project.id)
      .then((quotaRow) => {
        if (detailRequestRef.current !== requestId) {
          return
        }
        setStorageQuota(quotaRow)
        setQuotaInput(
          quotaRow.source === 'team' && quotaRow.quota_bytes !== null
            ? String(quotaRow.quota_bytes / 1024 ** 3)
            : '',
        )
      })
      .catch((error) => {
        if (detailRequestRef.current !== requestId) {
          return
        }
        setQuotaError(formatApiError(error))
      })
    try {
      const memberPromise = listProjectMembers(project.id)
      const invitationPromise =
        project.role === 'owner'
          ? listProjectInvitations(project.id)
          : Promise.resolve(null)
      const [memberRows, invitationRows] = await Promise.all([
        memberPromise,
        invitationPromise,
      ])
      if (detailRequestRef.current !== requestId) {
        return
      }
      setMembers(memberRows)
      if (invitationRows) {
        setPendingInvitations(invitationRows)
      } else {
        setPendingInvitations([])
      }
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
    if (detailLoadedForRef.current === routeProjectId) {
      return
    }
    detailLoadedForRef.current = routeProjectId
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
      setBanner({ tone: 'ok', text: `Team “${created.name}” created.` })
      setProjects((current) => [...current, created])
      navigate(`/teams/${created.id}`)
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  const onInvite = useCallback(
    async (event: React.FormEvent) => {
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
    },
    [
      selectedProject,
      isSelectedOwner,
      inviteEmail,
      inviteRole,
      refreshSelectedTeamDetail,
    ],
  )

  async function onSaveQuota(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedProject) {
      return
    }
    setBanner(null)
    const trimmed = quotaInput.trim()
    let bytes: number | null
    if (trimmed === '') {
      bytes = null
    } else {
      const gib = Number(trimmed)
      if (!Number.isFinite(gib) || gib < 1) {
        setBanner({
          tone: 'err',
          text: 'Enter a limit of at least 1 GiB, or clear the field for the platform default.',
        })
        return
      }
      bytes = Math.round(gib * 1024 ** 3)
    }
    setBusy(true)
    try {
      const updated = await updateProjectStorageQuota(
        selectedProject.id,
        bytes,
      )
      setStorageQuota(updated)
      setBanner({ tone: 'ok', text: 'Storage quota updated.' })
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  const onAcceptInvitation = useCallback(
    async (invitationId: string) => {
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
    },
    [refreshProjectsList, navigate],
  )

  const onRejectInvitation = useCallback(
    async (invitationId: string) => {
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
    },
    [refreshProjectsList],
  )

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
      setCancelInvitationTarget(null)
    }
  }

  const onChangeMemberRole = useCallback(
    async (userId: string, role: 'viewer' | 'operator') => {
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
    },
    [selectedProject, refreshSelectedTeamDetail],
  )

  const onRemoveMember = useCallback(
    (userId: string, email: string) => {
      if (!selectedProject) {
        return
      }
      setPendingAction({ kind: 'remove-member', userId, email })
    },
    [selectedProject],
  )

  const onLeaveTeam = useCallback(() => {
    if (!selectedProject || selectedProject.role === 'owner') {
      return
    }
    setPendingAction({
      kind: 'leave-team',
      teamLabel: teamDisplayName(selectedProject),
    })
  }, [selectedProject])

  async function onConfirmRemoveMember() {
    const action = pendingAction
    if (!selectedProject || action?.kind !== 'remove-member') {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      await removeProjectMember(selectedProject.id, action.userId)
      await refreshSelectedTeamDetail()
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
      setPendingAction(null)
    }
  }

  async function onConfirmLeaveTeam() {
    const action = pendingAction
    if (!selectedProject || action?.kind !== 'leave-team') {
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
      setPendingAction(null)
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
