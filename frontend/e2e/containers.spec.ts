import { expect, test } from '@playwright/test'

const mockContainer = {
  id: 'e2e-mock-id',
  name: 'e2e-mock',
  image: 'nginx:alpine',
  status: 'running',
  created_at: '2026-04-01T12:00:00.000Z',
  ports: [],
  labels: {},
  health: 'none',
}

const mockRunResponse = {
  container: mockContainer,
  kind: 'image',
  image: 'nginx:alpine',
  route_wired: true,
  public_url: 'https://vela-e2e.example.com/',
}

test.describe('Containers page (UI + mocked API)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/containers/**', async (route) => {
      const url = route.request().url()
      const method = route.request().method()

      if (method === 'GET' && /\/api\/containers\/?(\?.*)?$/.test(url)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
        return
      }

      if (method === 'POST' && url.includes('/api/containers/run')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockRunResponse),
        })
        return
      }

      await route.continue()
    })
  })

  test('shows create form, Build, and Running workloads', async ({ page }) => {
    await page.goto('/containers')
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 })
    ).toBeVisible()
    await expect(
      page.getByLabel(/Docker image reference or Git clone URL/i)
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Build' })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Running workloads', level: 2 })
    ).toBeVisible()
  })

  test('submitting the form shows success and public URL', async ({ page }) => {
    await page.goto('/containers')
    await page.getByLabel(/Docker image reference or Git clone URL/i).fill('nginx:alpine')
    await page.getByRole('button', { name: 'Build' }).click()
    await expect(page.getByRole('alert')).toContainText('Started')
    await expect(
      page.getByRole('link', { name: mockRunResponse.public_url })
    ).toBeVisible()
  })

  test('Git branch field appears for https source', async ({ page }) => {
    await page.goto('/containers')
    const input = page.getByLabel(/Docker image reference or Git clone URL/i)
    await input.fill('https://github.com/org/repo.git')
    await expect(page.getByLabel('Git branch')).toBeVisible()
  })
})
