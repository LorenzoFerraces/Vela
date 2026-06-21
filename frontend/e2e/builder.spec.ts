import { expect, test } from './fixtures'
import { createDockerfileTemplate } from './api-helpers'

test.describe('Builder page', () => {
  test('shows Dockerfile templates section', async ({ authenticatedPage }) => {
    const templateName = `web-app-${Date.now()}`
    const createResponse = await createDockerfileTemplate(
      authenticatedPage,
      templateName,
      'FROM node:20-alpine\nWORKDIR /app\n',
    )
    expect(createResponse.ok()).toBeTruthy()

    await authenticatedPage.goto('/builder')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Builder', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Dockerfile templates',
        level: 2,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: templateName }),
    ).toBeVisible()
  })

  test('can edit and save a Dockerfile template', async ({
    authenticatedPage,
  }) => {
    const templateName = `edit-me-${Date.now()}`
    const createResponse = await createDockerfileTemplate(
      authenticatedPage,
      templateName,
      'FROM node:20-alpine\nWORKDIR /app\n',
    )
    expect(createResponse.ok()).toBeTruthy()

    await authenticatedPage.goto('/builder')
    await authenticatedPage.getByRole('button', { name: templateName }).click()
    const editor = authenticatedPage.locator('#edit-template-contents')
    await editor.fill('FROM node:22-alpine\n')
    await authenticatedPage
      .getByRole('button', { name: 'Save changes' })
      .click()
    await expect(
      authenticatedPage
        .getByRole('alert')
        .filter({ hasText: 'Dockerfile template saved' }),
    ).toBeVisible()
  })
})
