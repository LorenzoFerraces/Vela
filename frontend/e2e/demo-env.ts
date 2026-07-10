import {
  E2E_USER_EMAIL,
  E2E_USER_PASSWORD,
  apiBase,
  appBase,
} from './constants'

/** True when recording against manually started dev/prod servers (see playwright.demo.live.config.ts). */
export function isLiveDemo(): boolean {
  return process.env.VELA_DEMO_LIVE === '1'
}

export const demoCredentials = {
  email: process.env.VELA_DEMO_EMAIL?.trim() || E2E_USER_EMAIL,
  password: process.env.VELA_DEMO_PASSWORD?.trim() || E2E_USER_PASSWORD,
}

/** Git repo shown in the Git-analysis scene (query + combobox label). */
export const demoGitRepo = {
  searchText:
    process.env.VELA_DEMO_GIT_SEARCH?.trim() || 'github.com/org/repo',
  optionLabel: process.env.VELA_DEMO_GIT_OPTION?.trim() || 'org/repo',
}

/** When set, Settings asserts this GitHub login; otherwise only checks the GitHub section exists. */
export const demoGitHubLogin = process.env.VELA_DEMO_GITHUB_LOGIN?.trim() || null

export function demoPublicUrlPattern(): RegExp {
  const custom = process.env.VELA_DEMO_PUBLIC_URL_PATTERN?.trim()
  if (custom) {
    return new RegExp(custom)
  }
  if (isLiveDemo()) {
    return /https?:\/\/[^\s]+/
  }
  return /https:\/\/.*apps\.e2e\.test\//
}

/** Skip seeding a stopped container for dashboard "problem first" ordering. */
export function demoSkipStoppedSeed(): boolean {
  return process.env.VELA_DEMO_SKIP_STOPPED_SEED === '1'
}

export const demoTimeouts = {
  test: isLiveDemo() ? 900_000 : 480_000,
  buildSuccess: isLiveDemo() ? 300_000 : 90_000,
  gitAnalyze: isLiveDemo() ? 180_000 : 30_000,
  imageAvailability: isLiveDemo() ? 120_000 : 30_000,
} as const

export const demoApiBase =
  process.env.VELA_DEMO_API_URL?.trim() ||
  (isLiveDemo() ? 'http://127.0.0.1:8000' : apiBase)

export const demoAppBase =
  process.env.VELA_DEMO_APP_URL?.trim() ||
  (isLiveDemo() ? 'http://127.0.0.1:5173' : appBase)

export const demoVideoFilename = isLiveDemo()
  ? 'vela-demo-live.webm'
  : 'vela-demo.webm'
