import { expect, test } from './fixtures'

test.describe('Terminal', () => {
  test('terminal button opens terminal for running container', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')

    const terminalButton = authenticatedPage.getByRole('button', {
      name: 'Open terminal',
    })

    if (await terminalButton.count() === 0) {
      test.skip('no running container available')
    }

    await terminalButton.click()
    await expect(authenticatedPage.locator('.workloads-terminal')).toBeVisible()
  })
})
