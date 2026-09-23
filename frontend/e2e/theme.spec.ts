import { expect, test } from './fixtures'

test('theme toggle flips the document theme and survives reload', async ({
  authenticatedPage: page,
}) => {
  await page.goto('/dashboard')
  await page.evaluate(() => localStorage.setItem('vela.theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'light')

  await page.getByRole('button', { name: 'Toggle color theme' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})
