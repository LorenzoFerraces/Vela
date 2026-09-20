import { expect, test } from './fixtures'
import { deployImageContainer } from './api-helpers'

/**
 * In-flight UI assertions need a slow fake deploy; run this spec with:
 *   $env:VELA_FAKE_DEPLOY_DELAY_MS = "3000"; npm run test:e2e -- e2e/deploy-progress.spec.ts
 * The final-state tests pass in the default suite (no env var) too.
 */
const deployDelayActive = !!process.env.VELA_FAKE_DEPLOY_DELAY_MS

test.describe('Deploy progress (containers)', () => {
  // deployImageContainer defaults to the primary E2E user's credentials, so
  // these tests use the matching authenticatedPage fixture — a page logged in
  // as another user would never see the API-submitted job.
  test('job row is pinned while a deploy is in flight and resolves to the container', async ({
    authenticatedPage,
  }) => {
    test.skip(
      !deployDelayActive,
      'requires VELA_FAKE_DEPLOY_DELAY_MS for in-flight timing',
    )
    await authenticatedPage.goto('/containers')

    const deployPromise = deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `progress-job-${Date.now()}`,
    )
    const jobRow = authenticatedPage.locator('.deploy-job-row')
    await expect(jobRow).toBeVisible()
    await expect(jobRow.locator('.skeleton').first()).toBeVisible()

    const response = await deployPromise
    expect(response.ok()).toBeTruthy()
    const body = (await response.json()) as { container: { name: string } }
    await expect(jobRow).toHaveCount(0)
    await expect(
      authenticatedPage.getByRole('cell', {
        name: body.container.name,
        exact: true,
      }),
    ).toBeVisible()
  })

  test('deploy resolves to the container row with no leftover job row', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const response = await deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `progress-ok-${Date.now()}`,
    )
    expect(response.ok()).toBeTruthy()
    await expect(
      authenticatedPage.locator('.deploy-job-row'),
    ).toHaveCount(0)
  })

  test('job row survives an SPA route change mid-deploy', async ({
    authenticatedPage,
  }) => {
    test.skip(
      !deployDelayActive,
      'requires VELA_FAKE_DEPLOY_DELAY_MS for in-flight timing',
    )
    await authenticatedPage.goto('/containers')
    const deployPromise = deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `route-change-job-${Date.now()}`,
    )
    await expect(
      authenticatedPage.locator('.deploy-job-row'),
    ).toBeVisible()
    await authenticatedPage.getByRole('link', { name: 'Stacks' }).click()
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Stacks', level: 1 }),
    ).toBeVisible()
    await authenticatedPage.getByRole('link', { name: 'Containers' }).click()
    await expect(
      authenticatedPage.locator('.deploy-job-row'),
    ).toBeVisible()
    const response = await deployPromise
    expect(response.ok()).toBeTruthy()
  })
})
