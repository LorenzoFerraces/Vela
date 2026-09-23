import {
  appBase,
  E2E_ADMIN_EMAIL,
  E2E_ADMIN_PASSWORD,
  E2E_USER_PASSWORD,
} from './constants'
import { expect, loginAndSeedToken, test } from './fixtures'

const baseURL = appBase

test('admin provisions a student and student cannot open staff routes', async ({
  browser,
  page,
}) => {
  const studentEmail = `e2e-rbac-student-${Date.now()}@example.com`
  const adminContext = await browser.newContext()
  const adminPage = await adminContext.newPage()

  await loginAndSeedToken(adminPage, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
  await adminPage.goto('/admin')
  await expect(adminPage.getByRole('heading', { name: 'Admin', level: 1 })).toBeVisible()

  await adminPage.getByRole('button', { name: 'Create user' }).click()
  const createUserDialog = adminPage.getByRole('dialog', { name: 'Create user' })
  await createUserDialog.getByLabel('Email').fill(studentEmail)
  await createUserDialog.getByLabel('Password').fill(E2E_USER_PASSWORD)
  await createUserDialog.getByLabel('Role').selectOption('student')
  await createUserDialog.getByRole('button', { name: 'Create user', exact: true }).click()
  await expect(
    adminPage.getByRole('status').filter({ hasText: 'User created' }),
  ).toBeVisible()

  await adminPage.getByRole('button', { name: E2E_ADMIN_EMAIL, exact: true }).click()
  await adminPage.getByRole('button', { name: 'Log out', exact: true }).click()
  await expect(adminPage).toHaveURL(`${baseURL}/login?next=%2Fadmin`)
  await adminContext.close()

  await page.goto('/login')
  await page.getByLabel('Email').fill(studentEmail)
  await page.getByLabel('Password').fill(E2E_USER_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(`${baseURL}/containers`)
  await expect(page.getByRole('button', { name: studentEmail, exact: true })).toBeVisible()

  const mainNav = page.getByRole('navigation', { name: 'Main' })
  await expect(mainNav.getByRole('link', { name: 'Teams' })).toHaveCount(0)
  await expect(mainNav.getByRole('link', { name: 'Admin' })).toHaveCount(0)

  for (const path of ['/teams', '/admin']) {
    await page.goto(path)
    await expect(page).toHaveURL(`${baseURL}/dashboard`)
  }
})

test('instructor can open teams but not audit tab', async ({ instructorPage }) => {
  await instructorPage.goto('/dashboard')
  const mainNav = instructorPage.getByRole('navigation', { name: 'Main' })
  await expect(mainNav.getByRole('link', { name: 'Teams' })).toBeVisible()
  await expect(mainNav.getByRole('link', { name: 'Admin' })).toBeVisible()

  await mainNav.getByRole('link', { name: 'Admin' }).click()
  await expect(instructorPage.getByRole('heading', { name: 'Admin', level: 1 })).toBeVisible()
  await expect(instructorPage.getByRole('tab', { name: 'Audit', exact: true })).toHaveCount(0)
})

test('login page has no signup link', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('link', { name: /create an account/i })).toHaveCount(0)
})
