import type { GithubStatus } from '../../api/client'

export const IMAGE_REF_CHECK_DEBOUNCE_MS = 600

export const GITHUB_STATUS_DISCONNECTED: GithubStatus = {
  connected: false,
  login: null,
  avatar_url: null,
  scopes: [],
  connected_at: null,
}
