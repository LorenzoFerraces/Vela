import { expect, fakeUser, test } from './fixtures'

const connectedGithubStatus = {
  connected: true,
  login: 'vela-user',
  avatar_url: 'https://avatars.example.com/u/1',
  scopes: ['repo', 'read:user'],
  connected_at: '2026-03-15T10:00:00.000Z',
}

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
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'GitHub', level: 3 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Connect GitHub' }),
    ).toBeVisible()
  })

  test('renders the connected GitHub card with login, scopes, and Disconnect', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route(
      '**/api/auth/github/status',
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(connectedGithubStatus),
        })
      },
    )

    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByText(`@${connectedGithubStatus.login}`),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('list', {
        name: 'Granted GitHub scopes',
      }),
    ).toBeVisible()
    for (const scope of connectedGithubStatus.scopes) {
      await expect(authenticatedPage.getByText(scope, { exact: true })).toBeVisible()
    }
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
