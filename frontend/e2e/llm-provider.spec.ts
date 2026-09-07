import { bearerToken } from './auth-helpers'
import { apiBase } from './constants'
import { test, expect } from './fixtures'

test.describe('LLM provider settings', () => {
  test('renders the LLM provider card with Test disabled while no key is set', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'LLM provider', level: 3 }),
    ).toBeVisible()
    await expect(authenticatedPage.getByLabel('Provider')).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Test' }),
    ).toBeDisabled()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Save', exact: true }),
    ).toBeVisible()
  })

  test('saves an Anthropic provider and keeps it after reload', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByLabel('Provider').selectOption('anthropic')
    await authenticatedPage.getByLabel('API key').fill('sk-ant-e2e-test-key')
    await expect(authenticatedPage.getByLabel('Model')).toHaveValue(
      'claude-sonnet-4-5',
    )
    await authenticatedPage.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(authenticatedPage.getByText('LLM provider saved.')).toBeVisible()

    await authenticatedPage.reload()
    await expect(authenticatedPage.getByLabel('Provider')).toHaveValue('anthropic')
    await expect(authenticatedPage.getByLabel('API key')).toHaveAttribute(
      'placeholder',
      'Saved — leave blank to keep',
    )
  })

  test('removes the provider through the confirm dialog', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByRole('button', { name: 'Remove' }).click()
    const dialog = authenticatedPage.getByRole('dialog', {
      name: 'Remove LLM provider?',
    })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(
      authenticatedPage.getByText('LLM provider removed.'),
    ).toBeVisible()
  })

  test('cleans up the LLM provider row for later specs', async ({
    authenticatedPage,
  }) => {
    const token = await bearerToken(authenticatedPage)
    const response = await authenticatedPage.request.delete(
      `${apiBase}/api/settings/llm-provider`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(response.status()).toBe(204)
  })
})
