import type { Page } from '@playwright/test'

import { createDockerfileTemplate } from './api-helpers'
import { expect, test } from './fixtures'

async function seedDockerfileTemplate(page: Page, contents: string): Promise<string> {
  const name = `web-app-${Date.now()}`
  const response = await createDockerfileTemplate(page, name, contents)
  expect(response.ok()).toBeTruthy()
  return name
}

test.describe('Images page', () => {
  test('shows the Dockerfile templates section', async ({
    authenticatedPage,
  }) => {
    const templateName = await seedDockerfileTemplate(
      authenticatedPage,
      'FROM node:20-alpine\nWORKDIR /app\n',
    )

    await authenticatedPage.goto('/images')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Images', level: 1 }),
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
    const templateName = await seedDockerfileTemplate(
      authenticatedPage,
      'FROM node:20-alpine\nWORKDIR /app\n',
    )

    await authenticatedPage.goto('/images')
    await authenticatedPage
      .getByRole('button', { name: templateName })
      .click()
    const editor = authenticatedPage.locator('#edit-template-contents')
    await editor.fill('FROM node:22-alpine\n')
    await authenticatedPage
      .getByRole('button', { name: 'Save changes' })
      .click()
    await expect(
      authenticatedPage
        .getByRole('status')
        .filter({ hasText: 'Dockerfile template saved' }),
    ).toBeVisible()
  })
})
