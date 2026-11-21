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

/** Minimal view of a deploy job from GET /api/deploys/active. */
interface DeployJobView {
  job_id: string
  status: 'in_progress' | 'succeeded' | 'failed'
  error?: { code: string; detail: string; build_log?: string | null } | null
  result?: Record<string, unknown> | null
}

export async function waitForDeployJob(
  page: Page,
  token: string,
  jobId: string,
  timeoutMs = 30_000,
): Promise<DeployJobView> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const response = await page.request.get(`${apiBase}/api/deploys/active`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const jobs = (await response.json()) as DeployJobView[]
    const job = jobs.find((entry) => entry.job_id === jobId)
    if (job && job.status !== 'in_progress') {
      return job
    }
    if (Date.now() >= deadline) {
      throw new Error(`deploy job ${jobId} did not finish within ${timeoutMs}ms`)
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
}

/**
 * Synthetic Response-like object matching the APIResponse surface callers
 * use (`ok()`/`status()`/`json()` as methods). A real fetch `Response` does
 * not work here: in Node its `ok`/`status` are properties, and every spec
 * calls `response.ok()`.
 */
function syntheticResponse(status: number, payload: unknown) {
  return {
    ok: () => status >= 200 && status < 300,
    status: () => status,
    json: () => Promise.resolve(payload),
  }
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
  const response = await page.request.post(`${apiBase}/api/containers/run`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      source_kind: 'image',
      image_ref: imageRef,
      public_route: true,
      container_port: 80,
      container_name: containerName ?? null,
    },
  })
  if (!response.ok()) {
    return response
  }
  const accepted = (await response.json()) as { job_id: string }
  const job = await waitForDeployJob(page, token, accepted.job_id)
  if (job.status === 'failed') {
    return syntheticResponse(422, job.error ?? {})
  }
  return syntheticResponse(200, job.result ?? {})
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
