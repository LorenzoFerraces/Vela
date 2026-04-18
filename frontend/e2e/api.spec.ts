import { expect, test } from '@playwright/test'

/** Matches Playwright webServer (backend) default. */
const apiBase = process.env.PW_API_URL ?? 'http://127.0.0.1:8000'

test.describe('live backend API', () => {
  test('GET /api/health returns ok', async ({ request }) => {
    const res = await request.get(`${apiBase}/api/health`)
    expect(res.ok()).toBeTruthy()
    expect(await res.json()).toEqual({ status: 'ok' })
  })
})
