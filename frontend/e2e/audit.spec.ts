import { bearerToken } from './auth-helpers'
import { apiBase } from './constants'
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
      .getByRole('button', { name: 'Audit Log' })
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

  test('renders with a malformed from date URL param', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/audit?from=not-a-date')

    await expect(
      authenticatedPage.getByRole('heading', { name: 'Audit Log', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('From date'),
    ).toBeVisible()
  })

  test('audit entries are strictly per-user', async ({
    authenticatedPage,
    authenticatedPageNoGithub,
  }) => {
    const token = await bearerToken(authenticatedPage)
    const seedResponse = await authenticatedPage.request.patch(
      `${apiBase}/api/users/me`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { pronouns: 'they/them' },
      },
    )
    expect(seedResponse.ok()).toBeTruthy()

    await authenticatedPage.goto('/audit')
    await expect(
      authenticatedPage.getByText('Updated profile'),
    ).toBeVisible()

    await authenticatedPageNoGithub.goto('/audit')
    await expect(
      authenticatedPageNoGithub.getByText('No audit entries found'),
    ).toBeVisible()
  })
})
