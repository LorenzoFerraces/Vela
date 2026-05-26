import { expect, test } from '@playwright/test'

import { apiBase } from './constants'

test.describe('live backend API', () => {
  test('GET /api/health returns ok', async ({ request }) => {
    const res = await request.get(`${apiBase}/api/health`)
    expect(res.ok()).toBeTruthy()
    expect(await res.json()).toEqual({ status: 'ok' })
  })
})
