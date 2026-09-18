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
} from '../../api/client'
import { teamDisplayName } from '../../projects/teamDisplay'

type Banner = { tone: 'ok' | 'err'; text: string } | null

export function useTeamManagement() {
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

  return {
    selectedProject,
    isSelectedOwner,
    loading,
    detailLoading,
    busy,
    banner,
    setBanner,
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
  }
}
