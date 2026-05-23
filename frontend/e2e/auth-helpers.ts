import type { Page } from '@playwright/test'
import { expect } from '@playwright/test'

import { apiBase, E2E_USER_EMAIL, E2E_USER_PASSWORD } from './constants'

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

export async function bearerToken(page: Page): Promise<string> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem('vela.access_token'),
  )
  if (!token) {
    throw new Error('Expected an access token in localStorage.')
  }
  return token
}
