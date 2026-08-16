import { expect, test } from './fixtures'

test.describe('Logs page', () => {
  test('loads logs page with filters and export', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs')
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Logs',
        level: 1,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Export CSV' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByPlaceholder('Search logs...'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('combobox'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByPlaceholder('Container ID...'),
    ).toBeVisible()
  })

  test('shows error for a container the user does not have', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs')
    await authenticatedPage
      .getByPlaceholder('Container ID...')
      .fill('nonexistent-id')
    await expect(
      authenticatedPage.getByText(/Container not found/),
    ).toBeVisible()
  })
})
