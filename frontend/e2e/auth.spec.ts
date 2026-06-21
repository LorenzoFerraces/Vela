import { appBase, E2E_USER_EMAIL, E2E_USER_PASSWORD } from './constants'
import { expect, test } from './fixtures'

/**
 * These tests intentionally do NOT use the `authenticatedPage` fixture, because
 * they exercise the login/register flow itself: they need to start anonymous
 * and drive the real forms against the live API.
 */

const baseURL = appBase

test.describe('protected routes', () => {
  test('hitting a protected route while logged out redirects to /login with next', async ({
    page,
  }) => {
    await page.goto('/containers')
    await expect(page).toHaveURL(/\/login\?next=%2Fcontainers/)
    await expect(
      page.getByRole('heading', { name: 'Sign in to Vela' }),
    ).toBeVisible()
  })
})

test.describe('login form', () => {
  test('successful login redirects to the requested next path', async ({
    page,
  }) => {
    await page.goto('/login?next=%2Fcontainers')
    await page.getByLabel('Email').fill(E2E_USER_EMAIL)
    await page.getByLabel('Password').fill(E2E_USER_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page).toHaveURL(`${baseURL}/containers`)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
  })

  test('invalid credentials surface a friendly message', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(E2E_USER_EMAIL)
    await page.getByLabel('Password').fill('wrong-password-value')
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'Invalid email or password.',
    )
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('registration form', () => {
  test('client-side validation blocks short passwords without hitting the API', async ({
    page,
  }) => {
    await page.goto('/register')
    await page.getByLabel('Email').fill('new.user@example.com')
    await page.getByLabel('Password').fill('short')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'Password must be at least 8 characters.',
    )
    await expect(page).toHaveURL(/\/register/)
  })

  test('successful registration lands on /containers', async ({ page }) => {
    const email = `register.${Date.now()}@example.com`

    await page.goto('/register')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('a-long-enough-password')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page).toHaveURL(`${baseURL}/containers`)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
  })

  test('duplicate email is rejected with a clear error', async ({ page }) => {
    await page.goto('/register')
    await page.getByLabel('Email').fill(E2E_USER_EMAIL)
    await page.getByLabel('Password').fill('a-long-enough-password')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'That email is already registered.',
    )
  })
})
