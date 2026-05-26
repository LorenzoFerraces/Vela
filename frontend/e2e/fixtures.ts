import { test as baseTest, expect, type Page } from '@playwright/test'

import { loginAndSeedToken } from './auth-helpers'
import {
  E2E_USER_EMAIL,
  E2E_USER_ID,
  E2E_USER_NO_GITHUB_EMAIL,
  E2E_USER_NO_GITHUB_PASSWORD,
} from './constants'

/**
 * Shared Playwright fixtures for Vela's UI tests.
 *
 * Authenticated tests log in against the real API started by Playwright's
 * webServer (see playwright.config.ts). No `/api/**` stubs for app flows.
 */

export const fakeUser = {
  id: E2E_USER_ID,
  email: E2E_USER_EMAIL,
  created_at: '2026-01-15T12:00:00.000Z',
}

export { loginAndSeedToken }

type AuthenticatedFixtures = {
  authenticatedPage: Page
  authenticatedPageNoGithub: Page
}

export const test = baseTest.extend<AuthenticatedFixtures>({
  authenticatedPage: async ({ page }, use) => {
    await loginAndSeedToken(page)
    await use(page)
  },
  authenticatedPageNoGithub: async ({ page }, use) => {
    await loginAndSeedToken(
      page,
      E2E_USER_NO_GITHUB_EMAIL,
      E2E_USER_NO_GITHUB_PASSWORD,
    )
    await use(page)
  },
})

export { expect }
