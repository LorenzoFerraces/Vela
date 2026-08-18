import { appBase } from './constants'
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
})
