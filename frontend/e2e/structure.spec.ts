import { deployImageContainer } from './api-helpers'
import { expect, test } from './fixtures'

test('home copy is English and theme-color follows the theme', async ({ authenticatedPage: page }) => {
  await page.goto('/')
  await expect(page.locator('.hero__eyebrow')).toHaveText('Deployment platform')
  const initial = await page.locator('meta[name="theme-color"]').getAttribute('content')
  await page.getByRole('button', { name: /toggle color theme/i }).click()
  await expect(page.locator('meta[name="theme-color"]')).not.toHaveAttribute('content', initial ?? '')
})

test('logs and exec WebSockets use a ticket, never access_token', async ({ authenticatedPage: page }) => {
  // Seed a running container through the existing E2E API helper — the fresh
  // /containers page has no container, so there would be no terminal button.
  const containerName = `ws-ticket-${Date.now()}`
  const deployed = await deployImageContainer(page, 'nginx:alpine', containerName)
  expect(deployed.ok()).toBeTruthy()
  const urls: string[] = []
  page.on('websocket', (socket) => urls.push(socket.url()))
  await page.goto('/containers')
  const row = page.locator('table.workloads-table tbody tr').filter({
    has: page.getByRole('cell', { name: containerName, exact: true }),
  })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: /terminal/i }).click()
  await expect.poll(() => urls.some((url) => url.includes('ticket='))).toBe(true)
  expect(urls.some((url) => url.includes('access_token='))).toBe(false)
})
