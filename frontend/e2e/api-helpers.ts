import type { Page } from '@playwright/test'

import {
  apiBase,
  E2E_USER_EMAIL,
  E2E_USER_PASSWORD,
} from './constants'

async function accessTokenForPage(
  page: Page,
  email: string = E2E_USER_EMAIL,
  password: string = E2E_USER_PASSWORD,
): Promise<string> {
  const response = await page.request.post(`${apiBase}/api/auth/login`, {
    data: { email, password },
  })
  if (!response.ok()) {
    throw new Error(`Login failed for ${email}: ${response.status()} ${await response.text()}`)
  }
  const body = (await response.json()) as { access_token: string }
  return body.access_token
}

export async function deployImageContainer(
  page: Page,
  imageRef: string,
  containerName?: string,
  credentials?: { email: string; password: string },
) {
  const token = await accessTokenForPage(
    page,
    credentials?.email,
    credentials?.password,
  )
  return page.request.post(`${apiBase}/api/containers/run`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      source_kind: 'image',
      image_ref: imageRef,
      public_route: true,
      container_port: 80,
      container_name: containerName ?? null,
    },
  })
}

export async function stopContainer(page: Page, containerId: string) {
  const token = await accessTokenForPage(page)
  return page.request.post(`${apiBase}/api/containers/${containerId}/stop`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function createDockerfileTemplate(
  page: Page,
  name: string,
  contents: string,
) {
  const token = await accessTokenForPage(page)
  return page.request.post(`${apiBase}/api/dockerfiles/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { name, contents },
  })
}
