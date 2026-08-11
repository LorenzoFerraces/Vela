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

  test('shows empty state when no logs', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs')
    await expect(authenticatedPage.getByText('No logs found')).toBeVisible()
  })
})
