import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPostEmpty,
  type ProjectRole,
} from './core'

export type Project = {
  id: string
  name: string
  is_personal: boolean
  role: ProjectRole
  owner_email: string
}

export type ProjectMember = {
  user_id: string
  email: string
  role: ProjectRole
  created_at: string
}

export type ProjectInvitation = {
  id: string
  invitee_user_id: string
  email: string
  role: 'operator' | 'viewer'
  created_at: string
}

export type IncomingProjectInvitation = {
  id: string
  project_id: string
  project_name: string
  inviter_email: string
  role: 'operator' | 'viewer'
  created_at: string
}

export async function listProjects(): Promise<Project[]> {
  return apiGet<Project[]>('/api/projects/', { cache: true })
}

export async function createProject(name: string): Promise<Project> {
  return apiPost<Project, { name: string }>('/api/projects/', { name })
}

export async function leaveProject(projectId: string): Promise<void> {
  await apiPostEmpty(
    `/api/projects/${encodeURIComponent(projectId)}/leave`,
  )
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return apiGet<ProjectMember[]>(`/api/projects/${encodeURIComponent(projectId)}/members`)
}

export async function listProjectInvitations(projectId: string): Promise<ProjectInvitation[]> {
  return apiGet<ProjectInvitation[]>(
    `/api/projects/${encodeURIComponent(projectId)}/invitations`
  )
}

export async function createProjectInvitation(
  projectId: string,
  body: { email: string; role: 'operator' | 'viewer' }
): Promise<ProjectInvitation> {
  return apiPost<ProjectInvitation, { email: string; role: 'operator' | 'viewer' }>(
    `/api/projects/${encodeURIComponent(projectId)}/invitations`,
    body
  )
}

export async function cancelProjectInvitation(
  projectId: string,
  invitationId: string
): Promise<void> {
  await apiDelete(
    `/api/projects/${encodeURIComponent(projectId)}/invitations/${encodeURIComponent(invitationId)}`
  )
}

export async function listIncomingInvitations(): Promise<IncomingProjectInvitation[]> {
  return apiGet<IncomingProjectInvitation[]>('/api/projects/invitations/incoming')
}

export async function acceptProjectInvitation(invitationId: string): Promise<Project> {
  return apiPost<Project>(
    `/api/projects/invitations/${encodeURIComponent(invitationId)}/accept`,
    {}
  )
}

export async function rejectProjectInvitation(invitationId: string): Promise<void> {
  await apiPostEmpty(
    `/api/projects/invitations/${encodeURIComponent(invitationId)}/reject`,
  )
}

export async function updateProjectMemberRole(
  projectId: string,
  userId: string,
  role: 'operator' | 'viewer'
): Promise<ProjectMember> {
  return apiPatch<ProjectMember, { role: 'operator' | 'viewer' }>(
    `/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
    { role }
  )
}

export async function removeProjectMember(
  projectId: string,
  userId: string
): Promise<void> {
  await apiDelete(
    `/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`
  )
}
