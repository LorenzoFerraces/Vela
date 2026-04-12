import { expect, test } from '@playwright/test'

const base = 'http://127.0.0.1:5173'

const navItems = [
  { label: 'Dashboard', path: '/dashboard', title: 'Dashboard' },
  { label: 'Containers', path: '/containers', title: 'Containers' },
  { label: 'Builder', path: '/builder', title: 'Builder' },
  { label: 'Images', path: '/images', title: 'Images' },
  { label: 'Settings', path: '/settings', title: 'Settings' },
] as const

test('welcome page shows Vela greeting', async ({ page }) => {
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Hola, esto es Vela' })
  ).toBeVisible()
  await expect(page.getByText('API: ok')).toBeVisible()
})

test('navbar navigates to placeholder sections', async ({ page }) => {
  await page.goto('/')

  for (const { label, path, title } of navItems) {
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: label }).click()
    await expect(page).toHaveURL(`${base}${path}`)
    await expect(
      page.getByRole('heading', { name: title, level: 1 })
    ).toBeVisible()
    if (path === '/containers') {
      await expect(
        page.getByLabel(/Docker image reference or Git clone URL/i)
      ).toBeVisible()
    } else {
      await expect(
        page.getByText('Esta sección estará disponible pronto.')
      ).toBeVisible()
    }
  }
})
