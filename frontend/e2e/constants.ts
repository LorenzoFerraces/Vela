/** Must stay in sync with `backend/app/e2e_support.py`. */

export const E2E_USER_EMAIL = 'e2e@example.com'
export const E2E_USER_PASSWORD = 'e2e-test-password-min-8'
export const E2E_USER_ID = '11111111-1111-1111-1111-111111111111'

export const E2E_USER_NO_GITHUB_EMAIL = 'e2e-nogithub@example.com'
export const E2E_USER_NO_GITHUB_PASSWORD = 'e2e-nogithub-password-min-8'

export const apiBase =
  process.env.PW_API_URL ?? `http://127.0.0.1:${process.env.PW_API_PORT ?? '8001'}`

/** Vite dev server origin for UI navigation assertions. */
export const appBase =
  process.env.PW_APP_URL ?? `http://127.0.0.1:${process.env.PW_VITE_PORT ?? '5174'}`
