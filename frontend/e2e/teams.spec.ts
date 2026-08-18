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
})
