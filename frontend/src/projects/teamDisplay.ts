import type { Project, ProjectRole } from '../api/client'

export function projectWriteAllowed(role: ProjectRole): boolean {
  return role === 'owner' || role === 'operator'
}

export function teamDisplayName(project: Project): string {
  if (project.is_personal && project.role === 'owner') {
    return 'Personal workspace'
  }
  if (project.is_personal) {
    return `${project.owner_email}'s workspace`
  }
  return project.name
}

export function teamDescription(project: Project): string {
  if (project.is_personal && project.role === 'owner') {
    return 'Your private workspace. Invite others to share your containers.'
  }
  if (project.is_personal) {
    return `Shared workspace owned by ${project.owner_email}.`
  }
  return 'Shared team workspace for containers and deployments.'
}
