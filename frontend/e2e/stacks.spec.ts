import { expect, test } from './fixtures'

test.describe('Stacks page', () => {
  test('lists stacks and supports create then deploy flow', async ({
    authenticatedPage,
  }) => {
    const stackName = `e2e-stack-${Date.now()}`

    await authenticatedPage.goto('/stacks')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Stacks', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'New Stack' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Import Compose' }),
    ).toHaveCount(0)

    await authenticatedPage.getByRole('button', { name: 'New Stack' }).click()
    const dialog = authenticatedPage.getByRole('dialog', { name: 'New Stack' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Manual' }).click()
    await expect(authenticatedPage).toHaveURL(/\/stacks\/new/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'New Stack', level: 1 }),
    ).toBeVisible()

    await authenticatedPage.getByLabel('Stack name').fill(stackName)
    await authenticatedPage.getByRole('button', { name: '+ Add Service' }).click()

    await authenticatedPage.getByLabel('Service name').fill('web')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('nginx')
    await authenticatedPage
      .getByRole('option', { name: 'nginx:alpine', exact: true })
      .click()
    await expect(
      authenticatedPage.getByText('Image reference found.'),
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Save Stack' }).click()
    await expect(authenticatedPage).toHaveURL(/\/stacks$/, { timeout: 15_000 })
    const card = authenticatedPage.locator('.stacks-card').filter({ hasText: stackName })
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Deploy' }).click()
    await expect(
      authenticatedPage.getByText('Stack deployed.'),
    ).toBeVisible({ timeout: 15_000 })

    await authenticatedPage.goto('/containers')
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Running workloads',
        level: 2,
      }),
    ).toBeVisible()
    await expect(authenticatedPage.getByText(`${stackName}_web`)).toBeVisible({
      timeout: 15_000,
    })
  })

  test('creates a stack from pasted compose in the modal', async ({
    authenticatedPage,
  }) => {
    const stackName = `e2e-modal-${Date.now()}`
    await authenticatedPage.goto('/stacks')
    await authenticatedPage.getByRole('button', { name: 'New Stack' }).click()
    const dialog = authenticatedPage.getByRole('dialog', { name: 'New Stack' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /From a file/i }).click()
    await dialog.getByLabel('Stack name').fill(stackName)
    await dialog.getByLabel(/manifest content/i).fill(`
 services:
   web:
     image: nginx:alpine
 `)
    await dialog.getByRole('button', { name: 'Parse' }).click()
    await expect(dialog.getByText(/From .*compose/i)).toBeVisible()
    await dialog.getByRole('button', { name: 'Create stack' }).click()
    await expect(
      authenticatedPage.locator('.stacks-card').filter({ hasText: stackName }),
    ).toBeVisible()
  })

  test('creates a stack from the e2e repo fixture in the modal', async ({
    authenticatedPage,
  }) => {
    const stackName = `e2e-repo-${Date.now()}`
    await authenticatedPage.goto('/stacks')
    await authenticatedPage.getByRole('button', { name: 'New Stack' }).click()
    const dialog = authenticatedPage.getByRole('dialog', { name: 'New Stack' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /From a repo/i }).click()
    await dialog
      .getByLabel('Git repository URL')
      .fill('https://github.com/org/repo.git')
    await dialog.getByRole('button', { name: 'Analyze repo' }).click()
    await expect(
      dialog.getByText('AI-generated — review carefully'),
    ).toBeVisible({ timeout: 30_000 })
    await expect(dialog.locator('.stacks-modal__service')).toHaveCount(2)
    await dialog.getByLabel('Stack name').fill(stackName)
    await dialog.getByRole('button', { name: 'Create stack' }).click()
    const card = authenticatedPage
      .locator('.stacks-card')
      .filter({ hasText: stackName })
    await expect(card).toBeVisible()
    await expect(card.getByText('2 services')).toBeVisible()
    await expect(
      authenticatedPage.getByText(`Stack '${stackName}' created.`),
    ).toBeVisible()
  })
})
