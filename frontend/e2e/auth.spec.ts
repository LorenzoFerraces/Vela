import { expect, fakeUser, test } from './fixtures'

/**
 * These tests intentionally do NOT use the `authenticatedPage` fixture, because
 * they exercise the login/register flow itself: they need to start anonymous
 * and drive the real forms.
 */

const baseURL = 'http://127.0.0.1:5173'

const loginSuccessResponse = {
  access_token: 'login.success.token',
  token_type: 'bearer',
  user: fakeUser,
}

const registerSuccessResponse = {
  access_token: 'register.success.token',
  token_type: 'bearer',
  user: { ...fakeUser, email: 'new.user@vela.test' },
}

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
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(loginSuccessResponse),
      })
    })
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fakeUser),
      })
    })
    // Containers page calls these on mount; stub them so the redirect lands
    // on a fully-rendered page.
    await page.route('**/api/auth/github/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connected: false,
          login: null,
          avatar_url: null,
          scopes: [],
          connected_at: null,
        }),
      })
    })
    await page.route('**/api/containers/', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    await page.goto('/login?next=%2Fcontainers')
    await page.getByLabel('Email').fill(fakeUser.email)
    await page.getByLabel('Password').fill('correcthorsebatterystaple')
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page).toHaveURL(`${baseURL}/containers`)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
  })

  test('invalid credentials surface a friendly message', async ({ page }) => {
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid credentials' }),
      })
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill('wrong@vela.test')
    await page.getByLabel('Password').fill('whatever')
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
    let registerCalled = false
    await page.route('**/api/auth/register', async (route) => {
      registerCalled = true
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(registerSuccessResponse),
      })
    })

    await page.goto('/register')
    await page.getByLabel('Email').fill('new.user@vela.test')
    await page.getByLabel('Password').fill('short')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'Password must be at least 8 characters.',
    )
    expect(registerCalled).toBe(false)
  })

  test('successful registration lands on /containers', async ({ page }) => {
    await page.route('**/api/auth/register', async (route) => {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(registerSuccessResponse),
      })
    })
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(registerSuccessResponse.user),
      })
    })
    await page.route('**/api/auth/github/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connected: false,
          login: null,
          avatar_url: null,
          scopes: [],
          connected_at: null,
        }),
      })
    })
    await page.route('**/api/containers/', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    await page.goto('/register')
    await page.getByLabel('Email').fill('new.user@vela.test')
    await page.getByLabel('Password').fill('a-long-enough-password')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page).toHaveURL(`${baseURL}/containers`)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
  })

  test('duplicate email is rejected with a clear error', async ({ page }) => {
    await page.route('**/api/auth/register', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Email already registered' }),
      })
    })

    await page.goto('/register')
    await page.getByLabel('Email').fill('taken@vela.test')
    await page.getByLabel('Password').fill('a-long-enough-password')
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'That email is already registered.',
    )
  })
})
