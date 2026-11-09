import { bearerToken } from './auth-helpers'
import { apiBase } from './constants'
import { expect, fakeUser, test } from './fixtures'

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
    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByLabel('Display name').fill('E2E User')
    await authenticatedPage.getByLabel('Pronouns').fill('they/them')
    await authenticatedPage.getByRole('button', { name: 'Save profile' }).click()
    await expect(authenticatedPage.getByText('Profile saved.')).toBeVisible()

    // Reset the profile so later specs still see display_name null (the user
    // menu trigger falls back to the email address).
    const token = await bearerToken(authenticatedPage)
    const resetResponse = await authenticatedPage.request.patch(
      `${apiBase}/api/users/me`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { display_name: null, pronouns: null },
      },
    )
    expect(resetResponse.ok()).toBeTruthy()
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

  test('toggling the email alerts master checkbox round-trips', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    const alerts = authenticatedPage.getByRole('checkbox', {
      name: 'Enable email alerts',
    })
    const initiallyChecked = await alerts.isChecked()
    await alerts.click()
    await expect(alerts).toBeChecked({ checked: !initiallyChecked })
    await alerts.click()
    await expect(alerts).toBeChecked({ checked: initiallyChecked })
  })
})
