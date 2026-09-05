import { appBase, E2E_USER_NO_GITHUB_EMAIL } from './constants'
import { expect, test } from './fixtures'

const baseURL = appBase

test.describe('teams page', () => {
  test('shows the storage section with the platform default', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto(`${baseURL}/teams`)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Storage', level: 3 }),
    ).toBeVisible()
    await expect(authenticatedPage.getByText('No limit')).toBeVisible()
    // The signed-in user owns their personal team, so the editor is visible.
    await expect(
      authenticatedPage.getByRole('button', { name: 'Save' }),
    ).toBeVisible()
  })

  test('saves the project storage quota', async ({ authenticatedPage }) => {
    await authenticatedPage.goto(`${baseURL}/teams`)
    const limitInput = authenticatedPage.getByLabel('Limit (GiB)')
    await expect(limitInput).toBeVisible()
    await limitInput.fill('2')
    await authenticatedPage
      .getByRole('button', { name: 'Save' })
      .click()
    await expect(
      authenticatedPage.getByText('Storage quota updated.'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByText(/of 2\.0 GiB used/),
    ).toBeVisible()
    await authenticatedPage.reload()
    await expect(limitInput).toHaveValue('2')
    await expect(
      authenticatedPage.getByText(/of 2\.0 GiB used/),
    ).toBeVisible()
  })

  test('blocks a storage quota below 1 GiB', async ({ authenticatedPage }) => {
    await authenticatedPage.goto(`${baseURL}/teams`)
    const limitInput = authenticatedPage.getByLabel('Limit (GiB)')
    await expect(limitInput).toBeVisible()
    await limitInput.fill('0.5')
    await authenticatedPage
      .getByRole('button', { name: 'Save' })
      .click()
    const alert = authenticatedPage.getByRole('alert')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('at least 1 GiB')
  })

  test('hides quota and invite controls from a non-owner member', async ({
    authenticatedPage,
    authenticatedPageNoGithub,
  }) => {
    await authenticatedPage.goto(`${baseURL}/teams`)
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Invite member',
        level: 3,
      }),
    ).toBeVisible()
    await authenticatedPage
      .getByLabel('Email')
      .fill(E2E_USER_NO_GITHUB_EMAIL)
    await authenticatedPage
      .getByRole('button', { name: 'Invite' })
      .click()
    await expect(
      authenticatedPage
        .getByRole('status')
        .filter({ hasText: 'Invitation sent' }),
    ).toBeVisible()

    await authenticatedPageNoGithub.goto(`${baseURL}/teams`)
    await expect(
      authenticatedPageNoGithub.getByRole('heading', {
        name: 'Incoming invitations',
      }),
    ).toBeVisible()
    await authenticatedPageNoGithub
      .getByRole('button', { name: 'Accept' })
      .click()
    await expect(
      authenticatedPageNoGithub
        .getByRole('status')
        .filter({ hasText: 'You joined' }),
    ).toBeVisible()
    await expect(
      authenticatedPageNoGithub.getByLabel('Limit (GiB)'),
    ).toHaveCount(0)
    await expect(
      authenticatedPageNoGithub.getByRole('button', { name: 'Save' }),
    ).toHaveCount(0)
    await expect(
      authenticatedPageNoGithub.getByText(/Your role: Viewer/),
    ).toBeVisible()
  })
})
