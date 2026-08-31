import { expect, test } from './fixtures'

test.describe('Audit log page', () => {
  test('opens from the user menu and shows filters and entry state', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/dashboard')
    await authenticatedPage
      .getByRole('button', { name: 'e2e@example.com' })
      .click()
    await authenticatedPage
      .getByRole('menuitem', { name: 'Audit Log' })
      .click()

    await expect(authenticatedPage).toHaveURL(/\/audit/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Audit Log', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Filter by action' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Filter by target type' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('From date'),
    ).toBeVisible()
    await expect(
      authenticatedPage
        .getByText(/Showing \d+ of \d+ entries|No audit entries found/)
        .first(),
    ).toBeVisible()
  })
})
