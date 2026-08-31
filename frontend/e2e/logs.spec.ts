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
    await authenticatedPage.getByRole('button', { name: 'Build' }).click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible()

    await authenticatedPage.getByRole('link', { name: 'Logs' }).first().click()
    await expect(authenticatedPage).toHaveURL(/\/logs\?container_id=/)
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Container' }),
    ).toHaveValue(/.+/)
    await expect(
      authenticatedPage.getByText(/Showing \d+ of \d+ entries/),
    ).toBeVisible()
  })

  test('shows an error for an unknown container id in the URL', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs?container_id=nonexistent-id')
    await expect(authenticatedPage.getByRole('alert')).toBeVisible()
  })

  test('renders with malformed start and end URL params', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs?start=garbage&end=garbage')

    await expect(
      authenticatedPage.getByRole('heading', { name: 'Logs', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('From'),
    ).toBeVisible()
  })
})
