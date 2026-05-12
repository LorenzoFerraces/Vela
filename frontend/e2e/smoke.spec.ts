import { expect, test } from './fixtures'

const baseURL = 'http://127.0.0.1:5173'

const protectedNavItems = [
  { label: 'Dashboard', path: '/dashboard', title: 'Dashboard' },
  { label: 'Containers', path: '/containers', title: 'Containers' },
  { label: 'Builder', path: '/builder', title: 'Builder' },
  { label: 'Images', path: '/images', title: 'Images' },
  { label: 'Settings', path: '/settings', title: 'Settings' },
] as const

test.describe('home page (anonymous)', () => {
  test('shows the Vela greeting and API health', async ({ page }) => {
    await page.goto('/')
    await expect(
      page.getByRole('heading', { name: 'Hola, esto es Vela' }),
    ).toBeVisible()
    await expect(page.getByText('API: ok')).toBeVisible()
  })

  test('navbar only offers a Log in entry point until you sign in', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(
      page.getByRole('link', { name: 'Log in' }),
    ).toBeVisible()
    await expect(
      page.getByRole('navigation', { name: 'Main' }),
    ).toHaveCount(0)
  })
})

test.describe('navbar (authenticated)', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    await authenticatedPage.route('**/api/containers/', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        })
        return
      }
      await route.continue()
    })
  })

  test('signed-in user can walk through every protected section', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/')

    for (const { label, path, title } of protectedNavItems) {
      await authenticatedPage
        .getByRole('navigation', { name: 'Main' })
        .getByRole('link', { name: label })
        .click()
      await expect(authenticatedPage).toHaveURL(`${baseURL}${path}`)
      await expect(
        authenticatedPage.getByRole('heading', { name: title, level: 1 }),
      ).toBeVisible()
      if (path === '/containers') {
        await expect(
          authenticatedPage.getByLabel(
            /Docker image reference or Git clone URL/i,
          ),
        ).toBeVisible()
      } else if (path === '/builder' || path === '/images') {
        await expect(
          authenticatedPage.getByText('Esta sección estará disponible pronto.'),
        ).toBeVisible()
      }
    }
  })

  test('signed-in user can log out and return to anonymous state', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/dashboard')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Dashboard', level: 1 }),
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Log out' }).click()
    await expect(authenticatedPage).toHaveURL(/\/login(\?.*)?$/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Sign in to Vela' }),
    ).toBeVisible()
  })
})
