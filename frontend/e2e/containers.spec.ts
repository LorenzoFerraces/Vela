import { expect, test } from './fixtures'

const mockContainer = {
  id: 'e2e-mock-id',
  name: 'e2e-mock',
  image: 'nginx:alpine',
  status: 'running',
  created_at: '2026-04-01T12:00:00.000Z',
  ports: [],
  labels: {},
  health: 'none',
  access_url: 'https://vela-e2e.example.com/',
}

const mockRunResponse = {
  container: mockContainer,
  kind: 'image',
  image: 'nginx:alpine',
  route_wired: true,
  public_url: 'https://vela-e2e.example.com/',
}

test.describe('Containers page (UI + mocked API)', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    // The Containers page touches several endpoints:
    //   - GET /api/containers/                    → list workloads
    //   - GET /api/containers/image/suggestions   → debounced image autocomplete
    //   - GET /api/containers/image/availability  → pre-flight before Build
    //   - POST /api/containers/run                → actual deploy
    // Mock them all from a single handler so the order in which routes were
    // registered does not matter.
    await authenticatedPage.route('**/api/containers/**', async (route) => {
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

      if (
        method === 'GET' &&
        url.includes('/api/containers/image/availability')
      ) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ref: 'nginx:alpine',
            available: true,
            checked: true,
            detail: null,
            can_attempt_deploy: true,
          }),
        })
        return
      }

      if (
        method === 'GET' &&
        url.includes('/api/containers/image/suggestions')
      ) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ suggestions: [] }),
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

  test('shows create form, Build, and Running workloads', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Containers',
        level: 1,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel(/Docker image reference or Git clone URL/i),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Build' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Running workloads',
        level: 2,
      }),
    ).toBeVisible()
  })

  test('submitting the form shows success and public URL', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel(
      /Docker image reference or Git clone URL/i,
    )
    await sourceInput.fill('nginx:alpine')
    await expect(
      authenticatedPage.getByText('Image reference found.'),
    ).toBeVisible()
    await authenticatedPage.getByRole('button', { name: 'Build' }).click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('link', { name: mockRunResponse.public_url }),
    ).toBeVisible()
  })

  test('Git branch field appears for https source', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel(
      /Docker image reference or Git clone URL/i,
    )
    await sourceInput.fill('https://github.com/org/repo.git')
    await expect(
      authenticatedPage.getByLabel('Git branch'),
    ).toBeVisible()
  })
})
