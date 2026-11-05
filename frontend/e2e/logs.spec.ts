import { deployImageContainer } from './api-helpers'
import { bearerToken } from './auth-helpers'
import { apiBase } from './constants'
import { expect, test } from './fixtures'

test.describe('Logs page', () => {
  test('shows the container picker and empty state when no container is selected', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Logs', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Export CSV' }),
    ).toBeDisabled()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Container' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByPlaceholder('Search logs…'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByText('Select a container to view logs'),
    ).toBeVisible()
  })

  test('loads the log view for the container linked from the workloads table', async ({
    authenticatedPage,
  }) => {
    const containerName = `logs-link-${Date.now()}`
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('nginx')
    await authenticatedPage
      .getByRole('option', { name: 'nginx:alpine', exact: true })
      .click()
    await expect(
      authenticatedPage.getByText('Image reference found.'),
    ).toBeVisible()
    await authenticatedPage
      .getByLabel('Container name (optional)')
      .fill(containerName)
    await authenticatedPage.getByRole('button', { name: 'Build' }).click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible()

    const row = authenticatedPage
      .locator('table.workloads-table tbody tr')
      .filter({
        has: authenticatedPage.getByRole('cell', {
          name: containerName,
          exact: true,
        }),
      })
    await row.getByRole('link', { name: 'Logs' }).click()
    await expect(authenticatedPage).toHaveURL(/\/logs\?container_id=/)
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Container' }),
    ).toHaveValue(/.+/)
    await expect(
      authenticatedPage.getByText(/Showing \d+ of \d+ entries/),
    ).toBeVisible()
  })

  test('rejects another user from the container logs API', async ({
    authenticatedPage,
    authenticatedPageNoGithub,
  }) => {
    const deployResponse = await deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `logs-deny-${Date.now()}`,
    )
    expect(deployResponse.ok()).toBeTruthy()
    const deployBody = (await deployResponse.json()) as {
      container: { id: string }
    }

    const token = await bearerToken(authenticatedPageNoGithub)
    const logsResponse = await authenticatedPageNoGithub.request.get(
      `${apiBase}/api/logs/?container_id=${deployBody.container.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(logsResponse.status()).toBe(404)
  })

  test('shows an error for an unknown container id in the URL', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs?container_id=nonexistent-id')
    await expect(authenticatedPage.getByRole('alert')).toBeVisible()
  })

  test('renders with an unknown container and malformed start and end URL params', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage
      .goto('/logs?container_id=nonexistent-id&start=garbage&end=garbage')

    await expect(
      authenticatedPage.getByRole('heading', { name: 'Logs', level: 1 }),
    ).toBeVisible()
    const alert = authenticatedPage.getByRole('alert')
    await expect(alert).toBeVisible()
    await expect(alert).not.toHaveText(/Invalid time value/)
  })
})
