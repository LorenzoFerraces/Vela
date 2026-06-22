import { expect, fakeUser, test } from './fixtures'

const connectedGithubStatus = {
  connected: true,
  login: 'vela-user',
  avatar_url: 'https://avatars.example.com/u/1',
  scopes: ['repo', 'read:user'],
  connected_at: '2026-03-15T10:00:00.000Z',
}

const profileUser = {
  ...fakeUser,
  display_name: 'E2E User',
  pronouns: 'they/them',
}

test.describe('Settings page', () => {
  test('shows the profile section with account info from the signed-in user', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Settings', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Profile', level: 2 }),
    ).toBeVisible()
    const emailRow = authenticatedPage
      .locator('.settings-card__row')
      .filter({ hasText: 'Email' })
    await expect(emailRow.getByRole('definition')).toHaveText(fakeUser.email)
  })

  test('saves display name and pronouns via PATCH /api/users/me', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route('**/api/users/me', async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(profileUser),
        })
        return
      }
      await route.continue()
    })

    await authenticatedPage.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(profileUser),
      })
    })

    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByLabel('Display name').fill('E2E User')
    await authenticatedPage.getByLabel('Pronouns').fill('they/them')
    await authenticatedPage.getByRole('button', { name: 'Save profile' }).click()
    await expect(authenticatedPage.getByText('Profile saved.')).toBeVisible()
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

  test('renders AI deploy analysis preferences', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'AI deploy analysis', level: 3 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('checkbox', { name: 'Container port' }),
    ).toBeChecked()
  })
})
