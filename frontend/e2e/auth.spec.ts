import {
  appBase,
  E2E_ADMIN_EMAIL,
  E2E_ADMIN_PASSWORD,
  E2E_USER_EMAIL,
  E2E_USER_PASSWORD,
} from './constants'
import { expect, loginAndSeedToken, test } from './fixtures'

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
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    await expect(page).toHaveURL(`${baseURL}/containers`)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
  })

  test('invalid credentials surface a friendly message', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(E2E_USER_EMAIL)
    await page.getByLabel('Password').fill('wrong-password-value')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    await expect(page.getByRole('alert')).toContainText(
      'Invalid email or password.',
    )
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('role-gated routes', () => {
  test('anonymous access preserves the requested next path', async ({ page }) => {
    for (const path of ['/teams?view=active', '/admin?tab=users']) {
      await page.goto(path)
      await expect(page).toHaveURL(
        `${baseURL}/login?next=${encodeURIComponent(path)}`,
      )
    }
  })

  test('students are redirected away from staff routes', async ({
    authenticatedPageNoGithub,
  }) => {
    for (const path of ['/teams', '/admin']) {
      await authenticatedPageNoGithub.goto(path)
      await expect(authenticatedPageNoGithub).toHaveURL(`${baseURL}/dashboard`)
    }
  })

  test('navbar entries reflect each role', async ({
    authenticatedPageNoGithub,
    instructorPage,
    browser,
  }) => {
    await authenticatedPageNoGithub.goto('/dashboard')
    const studentNav = authenticatedPageNoGithub.getByRole('navigation', {
      name: 'Main',
    })
    await expect(studentNav.getByRole('link', { name: 'Teams' })).toHaveCount(0)
    await expect(studentNav.getByRole('link', { name: 'Admin' })).toHaveCount(0)

    await instructorPage.goto('/dashboard')
    const instructorNav = instructorPage.getByRole('navigation', { name: 'Main' })
    await expect(instructorNav.getByRole('link', { name: 'Teams' })).toBeVisible()
    await instructorNav.getByRole('link', { name: 'Admin' }).click()
    await expect(instructorPage).toHaveURL(`${baseURL}/admin`)
    await expect(
      instructorPage.getByRole('heading', { name: 'Admin', level: 1 }),
    ).toBeVisible()

    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await loginAndSeedToken(adminPage, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    await adminPage.goto('/admin')
    await expect(
      adminPage.getByRole('heading', { name: 'Admin', level: 1 }),
    ).toBeVisible()
    await adminContext.close()
  })
})

test('login has no public signup link', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByText('Create an account')).toHaveCount(0)
})
