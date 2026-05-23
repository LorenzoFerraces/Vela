import { expect, test } from './fixtures'

test.describe('Containers page', () => {
  test('shows create form, Build, and Running workloads', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Containers',
        level: 1,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('Deploy source'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Build' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Running workloads',
        level: 2,
      }),
    ).toBeVisible()
  })

  test('submitting the form shows success and public URL', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('nginx')
    await authenticatedPage
      .getByRole('option', { name: 'nginx:alpine' })
      .click()
    await expect(
      authenticatedPage.getByText('Image reference found.'),
    ).toBeVisible()
    await authenticatedPage.getByRole('button', { name: 'Build' }).click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('link', { name: /https:\/\/.*apps\.e2e\.test\// }),
    ).toBeVisible()
  })

  test('Git branch field appears for GitHub repo source', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('github.com/org/repo')
    await authenticatedPage.getByRole('option', { name: 'org/repo' }).click()
    await expect(
      authenticatedPage.getByLabel('Git branch'),
    ).toBeVisible()
  })
})
