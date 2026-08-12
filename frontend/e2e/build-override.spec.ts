import { expect, test } from './fixtures'

test.describe('Build override modal', () => {
  test('containers: needs_build_override opens modal then deploy succeeds', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')

    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('github.com/org/repo')
    await authenticatedPage.getByRole('option', { name: 'org/repo' }).click()
    await expect(authenticatedPage.getByLabel('Git branch')).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Build' }).click()

    const dialog = authenticatedPage.getByRole('dialog', {
      name: 'Build configuration',
    })
    await expect(dialog).toBeVisible({ timeout: 30_000 })

    await dialog.getByLabel('Language').selectOption('java')
    await expect(dialog.getByLabel('Package manager')).toBeVisible()
    await dialog.getByLabel('Package manager').selectOption('gradle')
    await dialog.getByRole('button', { name: 'Save build config' }).click()

    await expect(dialog).toBeHidden()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible({ timeout: 30_000 })
  })

  test('stacks: analyze needs_manual_build_config then override persists', async ({
    authenticatedPage,
  }) => {
    const stackName = `e2e-build-override-${Date.now()}`

    await authenticatedPage.goto('/stacks/new')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'New Stack', level: 1 }),
    ).toBeVisible()

    await authenticatedPage.getByLabel('Stack name').fill(stackName)
    await authenticatedPage.getByRole('button', { name: '+ Add Service' }).click()

    await authenticatedPage.getByLabel('Service name').fill('api')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('github.com/org/repo')
    await authenticatedPage.getByRole('option', { name: 'org/repo' }).click()

    await authenticatedPage.getByLabel('Git branch').fill('needs-manual')
    await authenticatedPage.getByRole('button', { name: 'Analyze repo' }).click()

    const dialog = authenticatedPage.getByRole('dialog', {
      name: 'Build configuration',
    })
    await expect(dialog).toBeVisible({ timeout: 15_000 })

    await dialog.getByLabel('Language').selectOption('java')
    await dialog.getByLabel('Package manager').selectOption('gradle')
    await dialog.getByRole('button', { name: 'Save build config' }).click()
    await expect(dialog).toBeHidden()

    await expect(
      authenticatedPage.getByText(/Build override:\s*Java.*gradle/i),
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Save Stack' }).click()
    await expect(authenticatedPage).toHaveURL(/\/stacks$/, { timeout: 15_000 })
    await expect(authenticatedPage.getByText(stackName)).toBeVisible()

    const row = authenticatedPage.locator('tr').filter({ hasText: stackName })
    await row.getByRole('button', { name: 'Edit' }).click()
    await expect(authenticatedPage).toHaveURL(/\/stacks\/[^/]+/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Edit Stack', level: 1 }),
    ).toBeVisible()
    await authenticatedPage
      .locator('.stacks-builder__list-item')
      .filter({ hasText: 'api' })
      .click()
    await expect(
      authenticatedPage.getByText(/Build override:\s*Java.*gradle/i),
    ).toBeVisible({ timeout: 15_000 })
  })
})
