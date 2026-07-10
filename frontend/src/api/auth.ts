/**
 * Authentication API endpoints for the Vela application.
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiRequest, apiUploadFile } from '../client'
import { UserPublic, UserProfileUpdate } from './types'

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  user: UserPublic
}

export interface RegisterRequest {
  email: string
  password: string
}

export interface LoginRequest {
  email: string
  password: string
}

export async function registerUser(
  body: RegisterRequest
): Promise<TokenResponse> {
  return apiPost<TokenResponse, RegisterRequest>(
    '/api/auth/register',
    body,
    { skipAuth: true }
  )
}

export async function login(body: LoginRequest): Promise<TokenResponse> {
  return apiPost<TokenResponse, LoginRequest>('/api/auth/login', body, {
    skipAuth: true,
  })
}

export async function getMe(): Promise<UserPublic> {
  return apiGet<UserPublic>('/api/auth/me')
}

export async function updateProfile(body: UserProfileUpdate): Promise<UserPublic> {
  return apiPatch<UserPublic, UserProfileUpdate>('/api/users/me', body)
}

export async function uploadAvatar(file: File): Promise<UserPublic> {
  const formData = new FormData()
  formData.append('file', file)
  return apiUploadFile<UserPublic>('/api/users/me/avatar', formData)
}

export async function deleteAvatar(): Promise<UserPublic> {
  return apiRequest<UserPublic>('/api/users/me/avatar', { method: 'DELETE' })
}

// --- GitHub OAuth ---

export interface GithubStatus {
  connected: boolean
  login: string | null
  avatar_url: string | null
  scopes: string[]
  connected_at: string | null
}

export interface GithubAuthorizeUrlResponse {
  authorize_url: string
}

export interface GithubRepo {
  full_name: string
  default_branch: string
  private: boolean
  html_url: string
  description: string | null
}

export interface GithubBranch {
  name: string
}

export async function getGithubStatus(): Promise<GithubStatus> {
  return apiGet<GithubStatus>('/api/auth/github/status')
}

const disconnectedGithubStatus: GithubStatus = {
  connected: false,
  login: null,
  avatar_url: null,
  scopes: [],
  connected_at: null,
}

/** Same as getGithubStatus but tolerates a cold API or brief network failures (e.g. right after dev server start). */
export async function getGithubStatusWithRetry(): Promise<GithubStatus> {
  const backoffMs = [0, 400, 1200]
  let lastError: unknown
  for (const wait of backoffMs) {
    if (wait > 0) {
      await new Promise((resolve) => setTimeout(resolve, wait))
    }
    if (!getAccessToken()) {
      return disconnectedGithubStatus
    }
    try {
      return await getGithubStatus()
    } catch (error) {
      lastError = error
    }
  }
  if (lastError !== undefined) {
    throw lastError
  }
  return disconnectedGithubStatus
}

export async function getGithubAuthorizeUrl(): Promise<GithubAuthorizeUrlResponse> {
  return apiGet<GithubAuthorizeUrlResponse>('/api/auth/github/start')
}

export async function disconnectGithub(): Promise<void> {
  await apiDelete('/api/auth/github')
}

export interface ListGithubReposParams {
  /** Server-side filter (GitHub search API). Prefer client-side filtering after fetchAllGithubRepos when browsing. */
  query?: string
  page?: number
  perPage?: number
}

export async function listGithubRepos(
  params?: ListGithubReposParams
): Promise<GithubRepo[]> {
  const page = params?.page ?? 1
  const perPage = Math.min(100, Math.max(1, params?.perPage ?? 30))
  const searchParams = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  })
  const trimmedQuery = params?.query?.trim()
  if (trimmedQuery) {
    searchParams.set('q', trimmedQuery)
  }
  return apiGet<GithubRepo[]>(`/api/github/repos?${searchParams.toString()}`)
}

const GITHUB_REPOS_FULL_FETCH_PAGE_SIZE = 100
const GITHUB_REPOS_FULL_FETCH_MAX_PAGES = 100

/** Load every repo page from ``GET /api/github/repos`` (no search query) for client-side filtering. */
export async function fetchAllGithubRepos(): Promise<GithubRepo[]> {
  const all: GithubRepo[] = []
  const seen = new Set<string>()
  for (let page = 1; page <= GITHUB_REPOS_FULL_FETCH_MAX_PAGES; page++) {
    const batch = await listGithubRepos({
      page,
      perPage: GITHUB_REPOS_FULL_FETCH_PAGE_SIZE,
    })
    for (const repo of batch) {
      if (repo.full_name && !seen.has(repo.full_name)) {
        seen.add(repo.full_name)
        all.push(repo)
      }
    }
    if (batch.length < GITHUB_REPOS_FULL_FETCH_PAGE_SIZE) {
      break
    }
  }
  return all
}

/**
 * Filter a list of GitHub repositories by a search query.
 *
 * The function trims `query` and, if non-empty, attempts a case-insensitive
 * `RegExp` match against each repo's `full_name` and `description`. If the
 * regex is invalid, it falls back to a case-insensitive substring search.
 * An empty or whitespace-only `query` returns the original `repos` array.
 *
 * @param repos - Array of repositories to filter
 * @param query - Search string or regular-expression pattern
 * @returns The repositories whose `full_name` or `description` match `query`
 */
export function filterGithubReposByQuery(
  repos: GithubRepo[],
  query: string
): GithubRepo[] {
  const trimmed = query.trim()
  if (!trimmed) {
    return repos
  }
  try {
    const pattern = new RegExp(trimmed, 'i')
    return repos.filter(
      (repo) =>
        pattern.test(repo.full_name) ||
        (repo.description !== null &&
          repo.description !== undefined &&
          pattern.test(repo.description))
    )
  } catch {
    const needle = trimmed.toLowerCase()
    return repos.filter(
      (repo) =>
        repo.full_name.toLowerCase().includes(needle) ||
        (repo.description?.toLowerCase().includes(needle) ?? false)
    )
  }
}

/**
 * Fetches the branches for a GitHub repository identified by its full name.
 *
 * @param fullName - The repository full name in the form `owner/repo`
 * @returns The list of repository branches
 * @throws Error when `fullName` is not in the `owner/repo` format
 */
export async function listGithubRepoBranches(
  fullName: string
): Promise<GithubBranch[]> {
  const slashIndex = fullName.indexOf('/')
  if (slashIndex <= 0 || slashIndex === fullName.length - 1) {
    throw new Error(`Invalid repo full_name: ${fullName}`)
  }
  const owner = encodeURIComponent(fullName.slice(0, slashIndex))
  const repo = encodeURIComponent(fullName.slice(slashIndex + 1))
  return apiGet<GithubBranch[]>(`/api/github/repos/${owner}/${repo}/branches`)
}