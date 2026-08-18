import { expect, test } from './fixtures'

test.describe('Terminal', () => {
  test('terminal opens and echoes a typed command', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')

    const terminalButton = authenticatedPage
      .getByRole('button', { name: 'Open terminal' })
      .first()

    if (!(await terminalButton.isVisible({ timeout: 5_000 }))) {
      const sourceInput = authenticatedPage.getByLabel('Deploy source')
      await sourceInput.click()
      await sourceInput.fill('nginx')
      await authenticatedPage
        .getByRole('option', { name: 'nginx:alpine', exact: true })
        .click()
      await expect(
        authenticatedPage.getByText('Image reference found.'),
      ).toBeVisible()
      await authenticatedPage.getByRole('button', { name: 'Build' }).click()
      await expect(
        authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
      ).toBeVisible()
    }

    await expect(terminalButton).toBeVisible({ timeout: 10_000 })
    await terminalButton.click()

    const pane = authenticatedPage.locator('.workloads-terminal')
    await expect(pane).toBeVisible()

    const input = pane.locator('.xterm-helper-textarea')
    await input.click()
    await input.pressSequentially('echo vela-e2e-ok\n', { delay: 20 })
    await expect(pane.locator('.xterm')).toContainText('echo vela-e2e-ok', {
      timeout: 10_000,
    })
  })
})
