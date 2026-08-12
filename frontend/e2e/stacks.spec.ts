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
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'New Stack' }).click()
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
    await expect(authenticatedPage.getByText(stackName)).toBeVisible()

    const row = authenticatedPage.locator('tr').filter({ hasText: stackName })
    await row.getByRole('button', { name: 'Deploy' }).click()
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

  test('parses compose, reviews services, then saves from builder', async ({
    authenticatedPage,
  }) => {
    const stackName = `e2e-import-${Date.now()}`

    await authenticatedPage.goto('/stacks/import')
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Import Docker Compose',
        level: 1,
      }),
    ).toBeVisible()

    await authenticatedPage.getByLabel('Stack name').fill(stackName)
    await authenticatedPage.getByLabel('docker-compose.yml content').fill(`
services:
  web:
    image: nginx:alpine
    environment:
      REDIS_HOST: redis
    depends_on:
      - redis
  redis:
    image: redis:7
`)
    await authenticatedPage.getByRole('button', { name: 'Parse' }).click()

    const dialog = authenticatedPage.getByRole('dialog', {
      name: 'Review imported services',
    })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel('Service name').first()).toHaveValue('web')
    await expect(dialog.getByText('Depends on: redis')).toBeVisible()
    await dialog.getByRole('button', { name: 'Continue to builder' }).click()

    await expect(authenticatedPage).toHaveURL(/\/stacks\/new/)
    await expect(authenticatedPage.getByLabel('Stack name')).toHaveValue(stackName)
    await expect(authenticatedPage.getByLabel('Service name')).toHaveValue('web')
    await expect(
      authenticatedPage.getByText('Service links'),
    ).toBeVisible()
    await expect(
      authenticatedPage.locator('.stacks-service-links').getByRole('button', {
        name: 'redis',
      }),
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Save Stack' }).click()
    await expect(authenticatedPage).toHaveURL(/\/stacks$/, { timeout: 15_000 })
    await expect(authenticatedPage.getByText(stackName)).toBeVisible()
  })
})
