import type { Page } from '@playwright/test'

import {
  apiBase,
  E2E_USER_EMAIL,
  E2E_USER_PASSWORD,
} from './constants'

/**
 * Obtain an API access token by logging in with the provided credentials.
 *
 * Uses the Playwright page request to POST to the authentication endpoint and returns the `access_token` from the JSON response.
 *
 * @param email - Email address to authenticate with; defaults to `E2E_USER_EMAIL` when omitted
 * @param password - Password to authenticate with; defaults to `E2E_USER_PASSWORD` when omitted
 * @returns The `access_token` string returned by the authentication endpoint
 * @throws Error if the login request is not successful; the error message includes the email used, HTTP status, and response body text
 */
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

/**
 * Starts a new container from the given image and exposes it with a public route.
 *
 * @param imageRef - Image reference to run (e.g., `owner/name:tag` or a registry URL)
 * @param containerName - Optional name for the created container; if omitted, no name is set
 * @param credentials - Optional credentials to authenticate the request; if omitted, E2E defaults are used
 * @returns The HTTP response returned by the containers run API endpoint
 */
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

/**
 * Stops a running container identified by its ID via the backend API.
 *
 * @param containerId - The ID of the container to stop.
 * @returns The Playwright API response for the stop request.
 */
export async function stopContainer(page: Page, containerId: string) {
  const token = await accessTokenForPage(page)
  return page.request.post(`${apiBase}/api/containers/${containerId}/stop`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

/**
 * Creates a Dockerfile template resource using the application's API.
 *
 * @param name - The name to assign to the Dockerfile template
 * @param contents - The Dockerfile contents to store in the template
 * @returns The server's HTTP response for the create request
 */
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
