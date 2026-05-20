import { expect, test } from './fixtures'

const mockSavedImage = {
  id: '11111111-1111-1111-1111-111111111101',
  ref: 'nginx:alpine',
  created_at: '2026-04-01T12:00:00.000Z',
}

const mockDockerfileTemplate = {
  id: '11111111-1111-1111-1111-111111111102',
  name: 'web-app',
  contents: 'FROM node:20-alpine\nWORKDIR /app\n',
  created_at: '2026-04-01T12:00:00.000Z',
  updated_at: '2026-04-01T12:00:00.000Z',
}

test.describe('Images page (UI + mocked API)', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    let savedImages = [mockSavedImage]
    let dockerfiles = [mockDockerfileTemplate]

    await authenticatedPage.route('**/api/saved-images/**', async (route) => {
      const url = route.request().url()
      const method = route.request().method()

      if (method === 'GET' && /\/api\/saved-images\/?(\?.*)?$/.test(url)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(savedImages),
        })
        return
      }

      if (method === 'POST' && /\/api\/saved-images\/?$/.test(url)) {
        const body = route.request().postDataJSON() as { ref: string }
        const created = {
          ...mockSavedImage,
          id: '11111111-1111-1111-1111-111111111199',
          ref: body.ref,
        }
        savedImages = [...savedImages, created]
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(created),
        })
        return
      }

      await route.continue()
    })

    await authenticatedPage.route('**/api/dockerfiles/**', async (route) => {
      const url = route.request().url()
      const method = route.request().method()

      if (method === 'GET' && /\/api\/dockerfiles\/?(\?.*)?$/.test(url)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(dockerfiles),
        })
        return
      }

      if (
        method === 'PATCH' &&
        url.includes(`/api/dockerfiles/${mockDockerfileTemplate.id}`)
      ) {
        const body = route.request().postDataJSON() as {
          contents?: string
          name?: string
        }
        dockerfiles = [
          {
            ...mockDockerfileTemplate,
            contents: body.contents ?? mockDockerfileTemplate.contents,
            name: body.name ?? mockDockerfileTemplate.name,
            updated_at: '2026-04-02T12:00:00.000Z',
          },
        ]
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(dockerfiles[0]),
        })
        return
      }

      await route.continue()
    })
  })

  test('shows saved images and Dockerfile sections', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/images')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Images', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Saved image references',
        level: 2,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('heading', {
        name: 'Dockerfile templates',
        level: 2,
      }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('cell', { name: 'nginx:alpine' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'web-app' }),
    ).toBeVisible()
  })

  test('can save a new image reference', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/images')
    await authenticatedPage.locator('#saved-image-ref').fill('redis:7')
    await authenticatedPage
      .getByRole('button', { name: 'Save reference' })
      .click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Saved redis:7' }),
    ).toBeVisible()
  })

  test('can edit and save a Dockerfile template', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/images')
    await authenticatedPage.getByRole('button', { name: 'web-app' }).click()
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
