import { apiGet, apiPatch, apiPost } from './core'
import type { AuditLogResponse } from './audit'

export interface AdminUserPublic {
  id: string
  email: string
  display_name: string | null
  role: 'admin' | 'instructor' | 'student'
  is_active: boolean
  created_at: string
}

export interface AdminUserListResponse {
  users: AdminUserPublic[]
  total: number
}

export interface AdminUserCreate {
  email: string
  password: string
  display_name?: string | null
  role: 'admin' | 'instructor' | 'student'
}

export interface AdminUserPatch {
  role?: 'admin' | 'instructor' | 'student'
  is_active?: boolean
}

export type AuditLogListResponse = AuditLogResponse

function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') searchParams.set(key, String(value))
  }
  const query = searchParams.toString()
  return query ? `?${query}` : ''
}

export function listAdminUsers(params: {
  query?: string
  role?: string
  is_active?: boolean
  limit?: number
  offset?: number
} = {}): Promise<AdminUserListResponse> {
  return apiGet<AdminUserListResponse>(`/api/admin/users${queryString(params)}`)
}

export function createAdminUser(body: AdminUserCreate): Promise<AdminUserPublic> {
  return apiPost<AdminUserPublic, AdminUserCreate>('/api/admin/users', body)
}

export function patchAdminUser(
  userId: string,
  body: AdminUserPatch,
): Promise<AdminUserPublic> {
  return apiPatch<AdminUserPublic, AdminUserPatch>(`/api/admin/users/${encodeURIComponent(userId)}`, body)
}

export function getGlobalAudit(params: { limit?: number; offset?: number } = {}): Promise<AuditLogListResponse> {
  return apiGet<AuditLogListResponse>(`/api/admin/audit${queryString(params)}`)
}

export type { AuditLogEntry, AuditLogResponse } from './audit'
