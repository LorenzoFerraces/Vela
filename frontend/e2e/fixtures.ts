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
  display_name: null,
  pronouns: null,
  avatar_url: null,
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
  authenticatedPageNoGithub: async ({ browser }, use) => {
    // Separate context, not just a second page: localStorage is per-context,
    // so both fixtures must not share storage or the last seeded token wins.
    const noGithubContext = await browser.newContext()
    const noGithubPage = await noGithubContext.newPage()
    await loginAndSeedToken(
      noGithubPage,
      E2E_USER_NO_GITHUB_EMAIL,
      E2E_USER_NO_GITHUB_PASSWORD,
    )
    await use(noGithubPage)
    await noGithubContext.close()
  },
})

export { expect }
