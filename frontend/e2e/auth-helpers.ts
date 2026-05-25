import type { Page } from '@playwright/test'
import { expect } from '@playwright/test'

import { apiBase, E2E_USER_EMAIL, E2E_USER_PASSWORD } from './constants'

/**
 * Authenticate with the application and store the returned access token in the page's localStorage.
 *
 * Performs a login request and seeds the received `access_token` into `window.localStorage` under the key `vela.access_token`
 * so subsequent page navigations or loads will have the token available.
 *
 * @param page - Playwright Page used to perform the login request and to inject the token into the browser context
 * @param email - The user email to authenticate with; defaults to `E2E_USER_EMAIL`
 * @param password - The user password to authenticate with; defaults to `E2E_USER_PASSWORD`
 */
export async function loginAndSeedToken(
  page: Page,
  email: string = E2E_USER_EMAIL,
  password: string = E2E_USER_PASSWORD,
) {
  const response = await page.request.post(`${apiBase}/api/auth/login`, {
    data: { email, password },
  })
  expect(response.ok()).toBeTruthy()
  const body = (await response.json()) as { access_token: string }
  await page.addInitScript((token) => {
    try {
      window.localStorage.setItem('vela.access_token', token)
    } catch {
      // localStorage can be unavailable in some sandboxed contexts.
    }
  }, body.access_token)
}

/**
 * Retrieve the access token previously stored in the page's localStorage.
 *
 * @returns The access token string stored under `vela.access_token`.
 * @throws Error if no access token is found in localStorage.
 */
export async function bearerToken(page: Page): Promise<string> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem('vela.access_token'),
  )
  if (!token) {
    throw new Error('Expected an access token in localStorage.')
  }
  return token
}
