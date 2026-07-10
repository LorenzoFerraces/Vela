/**
 * User management API endpoints for the Vela application.
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiUploadFile } from '../client'
import { UserPublic, UserProfileUpdate } from './types'

export interface UserPublic {
  id: string
  email: string
  created_at: string
  display_name: string | null
  pronouns: string | null
  avatar_url: string | null
}

export async function getUserProfile(): Promise<UserPublic> {
  return apiGet<UserPublic>('/api/users/me')
}

export async function updateUserProfile(body: UserProfileUpdate): Promise<UserPublic> {
  return apiPatch<UserPublic, UserProfileUpdate>('/api/users/me', body)
}

export async function uploadUserAvatar(file: File): Promise<UserPublic> {
  const formData = new FormData()
  formData.append('file', file)
  return apiUploadFile<UserPublic>('/api/users/me/avatar', formData)
}

export async function deleteUserAvatar(): Promise<UserPublic> {
  return apiRequest<UserPublic>('/api/users/me/avatar', { method: 'DELETE' })
}

export async function getUserById(userId: string): Promise<UserPublic> {
  return apiGet<UserPublic>(`/api/users/${encodeURIComponent(userId)}`)
}

export async function getAllUsers(): Promise<UserPublic[]> {
  return apiGet<UserPublic[]>('/api/users/')
}

export async function updateUserById(userId: string, body: UserProfileUpdate): Promise<UserPublic> {
  return apiPatch<UserPublic, UserProfileUpdate>(`/api/users/${encodeURIComponent(userId)}`, body)
}

export async function deleteUserById(userId: string): Promise<void> {
  await apiDelete(`/api/users/${encodeURIComponent(userId)}`)
}

export async function getProfile(): Promise<UserPublic> {
  return apiGet<UserPublic>('/api/users/me')
}