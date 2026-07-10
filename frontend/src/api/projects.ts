/**
 * Project management API endpoints for the Vela application.
 */
import { apiDelete, apiGet, apiPatch, apiPost } from '../client'
import { Project, ProjectInvitation, ProjectMember, IncomingProjectInvitation } from './types'

export type ProjectRole = 'owner' | 'operator' | 'viewer'

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
  return apiGet<Project[]>('/api/projects/')
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

export async function apiPostEmpty(path: string): Promise<void> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers({ Accept: 'application/json', 'Content-Type': 'application/json' })
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(url, { method: 'POST', headers, body: '{}' })
  await readEmptyOk(response)
}

export async function getProject(
  projectId: string
): Promise<Project> {
  return apiGet<Project>(`/api/projects/${encodeURIComponent(projectId)}`)
}

export async function updateProject(
  projectId: string,
  body: { name: string }
): Promise<Project> {
  return apiPatch<Project, { name: string }>(
    `/api/projects/${encodeURIComponent(projectId)}`,
    body
  )
}

export async function deleteProject(
  projectId: string
): Promise<void> {
  await apiDelete(`/api/projects/${encodeURIComponent(projectId)}`)
}

export async function getProjectMembers(
  projectId: string
): Promise<ProjectMember[]> {
  return apiGet<ProjectMember[]>(`/api/projects/${encodeURIComponent(projectId)}/members`)
}

export async function getProjectInvitations(
  projectId: string
): Promise<ProjectInvitation[]> {
  return apiGet<ProjectInvitation[]>(
    `/api/projects/${encodeURIComponent(projectId)}/invitations`
  )
}