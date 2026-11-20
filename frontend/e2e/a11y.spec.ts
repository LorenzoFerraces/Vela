import { E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD } from './constants'
import { expect, loginAndSeedToken, test } from './fixtures'

test('layout exposes a skip link to the main landmark', async ({ authenticatedPage: page }) => {
  await page.goto('/')
  const skip = page.getByRole('link', { name: /skip to main content/i })
  await expect(skip).toBeVisible()
  await skip.focus()
  await skip.press('Enter')
  await expect(page.locator('main#main-content')).toBeFocused()
})

test('admin tabs support arrow keys', async ({ page }) => {
  await loginAndSeedToken(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
  await page.goto('/admin')
  const usersTab = page.getByRole('tab', { name: 'Users' })
  await usersTab.focus()
  await usersTab.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Audit' })).toHaveAttribute('aria-selected', 'true')
})

test('stack builder confirms before discarding unsaved changes', async ({ authenticatedPage: page }) => {
  await page.goto('/stacks/new')
  await page.getByLabel('Stack name').fill('unsaved-stack')
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toMatch(/discard unsaved stack changes/i)
    await dialog.dismiss()
  })
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page).toHaveURL(/\/stacks\/new$/)
})
