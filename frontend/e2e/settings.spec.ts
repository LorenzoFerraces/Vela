import { expect, fakeUser, test } from './fixtures'

test.describe('Settings page', () => {
  test('shows the account info from the signed-in user', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Settings', level: 1 }),
    ).toBeVisible()
    const accountRow = authenticatedPage
      .locator('.settings-card__row')
      .filter({ hasText: 'Email' })
    await expect(accountRow.getByRole('definition')).toHaveText(fakeUser.email)
  })

  test('renders the disconnected GitHub card with a Connect button', async ({
    authenticatedPageNoGithub,
  }) => {
    await authenticatedPageNoGithub.goto('/settings')
    await expect(
      authenticatedPageNoGithub.getByRole('heading', { name: 'GitHub', level: 3 }),
    ).toBeVisible()
    await expect(
      authenticatedPageNoGithub.getByRole('button', { name: 'Connect GitHub' }),
    ).toBeVisible()
  })

  test('renders the connected GitHub card with login, scopes, and Disconnect', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByText('@vela-user'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('list', {
        name: 'Granted GitHub scopes',
      }),
    ).toBeVisible()
    await expect(authenticatedPage.getByText('repo', { exact: true })).toBeVisible()
    await expect(
      authenticatedPage.getByText('read:user', { exact: true }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Disconnect' }),
    ).toBeVisible()
  })

  test('surfaces the OAuth callback banner on ?github=connected', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings?github=connected')
    await expect(
      authenticatedPage.getByText('GitHub account connected.'),
    ).toBeVisible()
    await expect(authenticatedPage).toHaveURL(/\/settings$/)
  })
})
