import { test as baseTest, expect, type Page } from '@playwright/test'

/**
 * Shared Playwright fixtures for Vela's UI tests.
 *
 * Most of the app is behind email+password auth. Spinning up a real Postgres
 * user per test would be slow and would couple every UI assertion to the auth
 * stack, so these fixtures fake the signed-in state at the browser boundary:
 *
 *   - Pre-seed `localStorage` with a fake access token under the same key the
 *     real app uses (`vela.access_token`).
 *   - Mock `GET /api/auth/me` so the `AuthProvider` resolves to authenticated
 *     on first render.
 *
 * Tests that need to exercise the real login form skip the fixture and drive
 * the form directly (see `auth.spec.ts`).
 */

export const fakeAccessToken = 'fake.e2e.token'

export const fakeUser = {
  id: '11111111-1111-1111-1111-111111111111',
  email: 'e2e@vela.test',
  created_at: '2026-01-15T12:00:00.000Z',
}

export const disconnectedGithubStatus = {
  connected: false,
  login: null,
  avatar_url: null,
  scopes: [],
  connected_at: null,
}

/**
 * Install the standard backend mocks every authenticated UI test relies on:
 *
 *   - `/api/auth/me` returns the fake user
 *   - `/api/auth/github/status` returns "disconnected" so the Settings/Containers
 *     pages do not hang waiting for a real GitHub OAuth response
 *
 * Individual tests override more endpoints as needed (e.g. container list).
 */
async function installDefaultMocks(page: Page) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fakeUser),
    })
  })

  await page.route('**/api/auth/github/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(disconnectedGithubStatus),
    })
  })
}

/**
 * Seed the access token on the SPA origin before the app boots so
 * `AuthProvider` starts in the `loading` → `authenticated` path instead of
 * `anonymous`.
 */
async function seedAccessToken(page: Page) {
  await page.addInitScript((token) => {
    try {
      window.localStorage.setItem('vela.access_token', token)
    } catch {
      // localStorage can be unavailable in some sandboxed contexts.
    }
  }, fakeAccessToken)
}

type AuthenticatedFixtures = {
  authenticatedPage: Page
}

/**
 * `authenticatedPage` is a `Page` that the app will treat as a logged-in user
 * once it navigates anywhere. Default mocks for `/api/auth/me` and the GitHub
 * status endpoint are installed automatically.
 */
export const test = baseTest.extend<AuthenticatedFixtures>({
  authenticatedPage: async ({ page }, use) => {
    await seedAccessToken(page)
    await installDefaultMocks(page)
    await use(page)
  },
})

export { expect }
