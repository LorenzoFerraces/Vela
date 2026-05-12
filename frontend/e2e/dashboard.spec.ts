import { expect, test } from './fixtures'

const runningContainer = {
  id: 'dash-running-1',
  name: 'vela-web-1',
  image: 'nginx:alpine',
  status: 'running',
  created_at: '2026-04-01T12:00:00.000Z',
  ports: [],
  labels: {},
  health: 'healthy',
  access_url: null,
}

const stoppedContainer = {
  id: 'dash-stopped-1',
  name: 'vela-worker-1',
  image: 'python:3.12-slim',
  status: 'stopped',
  created_at: '2026-04-02T12:00:00.000Z',
  ports: [],
  labels: {},
  health: 'none',
  access_url: null,
}

test.describe('Dashboard page', () => {
  test('shows the empty-state copy when there are no containers', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route('**/api/containers/', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
        return
      }
      await route.continue()
    })

    await authenticatedPage.goto('/dashboard')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Dashboard', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByText('No Vela-managed containers yet.'),
    ).toBeVisible()
  })

  test('lists workloads and surfaces problem containers first', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route('**/api/containers/', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([runningContainer, stoppedContainer]),
        })
        return
      }
      await route.continue()
    })

    await authenticatedPage.goto('/dashboard')
    const tableRows = authenticatedPage.locator('table.workloads-table tbody tr')
    await expect(tableRows.first()).toBeVisible()

    await expect(tableRows.first()).toContainText(stoppedContainer.name)
    await expect(tableRows.first()).toContainText('stopped')
    await expect(tableRows.nth(1)).toContainText(runningContainer.name)
    await expect(tableRows.nth(1)).toContainText('running')
  })

  test('Refresh button triggers another list call', async ({
    authenticatedPage,
  }) => {
    let listCalls = 0
    await authenticatedPage.route('**/api/containers/', async (route) => {
      if (route.request().method() === 'GET') {
        listCalls += 1
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
        return
      }
      await route.continue()
    })

    await authenticatedPage.goto('/dashboard')
    await expect(
      authenticatedPage.getByText('No Vela-managed containers yet.'),
    ).toBeVisible()
    const callsAfterInitialLoad = listCalls

    await authenticatedPage.getByRole('button', { name: 'Refresh' }).click()
    await expect.poll(() => listCalls).toBeGreaterThan(callsAfterInitialLoad)
  })
})
