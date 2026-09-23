import { appBase, E2E_USER_NO_GITHUB_EMAIL } from './constants'
import { expect, test } from './fixtures'

const baseURL = appBase

test.describe('teams page', () => {
  test('shows the storage section with the platform default', async ({
    instructorPage,
  }) => {
    await instructorPage.goto(`${baseURL}/teams`)
    await expect(
      instructorPage.getByRole('heading', { name: 'Storage', level: 3 }),
    ).toBeVisible()
    await expect(instructorPage.getByText('No limit')).toBeVisible()
    await expect(
      instructorPage.getByRole('button', { name: 'Save' }),
    ).toBeVisible()
  })

  test('saves the project storage quota', async ({ instructorPage }) => {
    await instructorPage.goto(`${baseURL}/teams`)
    const limitInput = instructorPage.getByLabel('Limit (GiB)')
    await expect(limitInput).toBeVisible()
    await limitInput.fill('2')
    await instructorPage
      .getByRole('button', { name: 'Save' })
      .click()
    await expect(
      instructorPage.getByText('Storage quota updated.'),
    ).toBeVisible()
    await expect(
      instructorPage.getByText(/of 2\.0 GiB used/),
    ).toBeVisible()
    await instructorPage.reload()
    await expect(limitInput).toHaveValue('2')
    await expect(
      instructorPage.getByText(/of 2\.0 GiB used/),
    ).toBeVisible()
  })

  test('blocks a storage quota below 1 GiB', async ({ instructorPage }) => {
    await instructorPage.goto(`${baseURL}/teams`)
    const limitInput = instructorPage.getByLabel('Limit (GiB)')
    await expect(limitInput).toBeVisible()
    await limitInput.fill('0.5')
    await instructorPage
      .getByRole('button', { name: 'Save' })
      .click()
    const alert = instructorPage.getByRole('alert')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('at least 1 GiB')
  })

  test('keeps students outside team management', async ({
    instructorPage,
    authenticatedPageNoGithub,
  }) => {
    await instructorPage.goto(`${baseURL}/teams`)
    await instructorPage
      .getByLabel('Email')
      .fill(E2E_USER_NO_GITHUB_EMAIL)
    await instructorPage.getByRole('button', { name: 'Invite' }).click()
    await expect(
      instructorPage
        .getByRole('status')
        .filter({ hasText: 'Invitation sent' }),
    ).toBeVisible()

    await authenticatedPageNoGithub.goto(`${baseURL}/teams`)
    await expect(authenticatedPageNoGithub).toHaveURL(`${baseURL}/dashboard`)
  })
})
