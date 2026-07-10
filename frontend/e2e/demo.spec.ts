import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { deployImageContainer, stopContainer } from './api-helpers'
import {
  demoCredentials,
  demoGitHubLogin,
  demoGitRepo,
  demoPublicUrlPattern,
  demoSkipStoppedSeed,
  demoTimeouts,
  demoVideoFilename,
  isLiveDemo,
} from './demo-env'
import { DEMO_DWELL, dwell, fillSlowly } from './demo-helpers'
import { expect, test } from './fixtures'

const demoOutputDir = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'demo-recordings',
)
const demoVideoPath = path.join(demoOutputDir, demoVideoFilename)

/**
 * Silent ~5 minute product walkthrough for screen recording.
 *
 * E2E (self-contained):  `npm run demo:record`
 * Live (your dev stack):   `npm run demo:record:live` — see demo.live.env.example
 */
test.describe('Product demo recording', () => {
  test.describe.configure({ mode: 'serial', timeout: demoTimeouts.test })

  test('Vela product walkthrough (~5 min)', async ({ page }) => {
    test.setTimeout(demoTimeouts.test)

    // --- 1. Home (unauthenticated) ---
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Hola, esto es Vela' })).toBeVisible()
    await expect(page.getByText(/^API:/)).toBeVisible({ timeout: 30_000 })
    await dwell(page, DEMO_DWELL.scene)

    await page.getByRole('link', { name: 'Log in' }).click()
    await expect(page.getByRole('heading', { name: 'Sign in to Vela' })).toBeVisible()
    await dwell(page, DEMO_DWELL.beat)

    // --- 2. Sign in ---
    await fillSlowly(page.getByLabel('Email'), demoCredentials.email)
    await dwell(page, DEMO_DWELL.beat)
    await fillSlowly(page.getByLabel('Password'), demoCredentials.password)
    await dwell(page, DEMO_DWELL.form)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/\/containers/)
    await expect(
      page.getByRole('heading', { name: 'Containers', level: 1 }),
    ).toBeVisible()
    await dwell(page, DEMO_DWELL.scene)

    // --- 3. Deploy from image ---
    const sourceInput = page.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('nginx')
    await dwell(page, DEMO_DWELL.beat)
    await page.getByRole('option', { name: 'nginx:alpine', exact: true }).click()
    await expect(page.getByText('Image reference found.')).toBeVisible({
      timeout: demoTimeouts.imageAvailability,
    })
    await dwell(page, DEMO_DWELL.form)
    await page.getByRole('button', { name: 'Build' }).click()
    await expect(
      page.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible({ timeout: demoTimeouts.buildSuccess })
    await expect(
      page.getByRole('link', { name: demoPublicUrlPattern() }),
    ).toBeVisible()
    await dwell(page, DEMO_DWELL.highlight)

    // --- 4. Git repo analysis ---
    await sourceInput.click()
    await sourceInput.fill('')
    await sourceInput.fill(demoGitRepo.searchText)
    await dwell(page, DEMO_DWELL.beat)
    await page.getByRole('option', { name: demoGitRepo.optionLabel }).click()
    await expect(page.getByLabel('Git branch')).toBeVisible()
    await dwell(page, DEMO_DWELL.form)
    await page.getByRole('button', { name: 'Analyze repository' }).click()
    await expect(page.getByText('Analyzing repository…')).toBeHidden({
      timeout: demoTimeouts.gitAnalyze,
    })
    if (!isLiveDemo()) {
      await expect(page.getByLabel('Container port')).toHaveValue('5173')
    } else {
      const portInput = page.getByLabel('Container port')
      await expect(portInput).not.toHaveValue('80')
    }
    await dwell(page, DEMO_DWELL.highlight)

    if (!demoSkipStoppedSeed()) {
      const stoppedResponse = await deployImageContainer(
        page,
        'python:3.12-slim',
        `demo-stopped-${Date.now()}`,
      )
      expect(stoppedResponse.ok()).toBeTruthy()
      const stoppedBody = (await stoppedResponse.json()) as {
        container: { id: string }
      }
      const stopResponse = await stopContainer(page, stoppedBody.container.id)
      expect(stopResponse.ok()).toBeTruthy()
    }

    // --- 5. Dashboard ---
    await page.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()
    const tableRows = page.locator(
      '.workloads-table-wrap-outer table.workloads-table tbody tr',
    )
    await expect(tableRows.first()).toBeVisible({ timeout: demoTimeouts.buildSuccess })
    await dwell(page, DEMO_DWELL.scene)

    const firstShowLogs = tableRows.first().getByRole('button', { name: 'Show' })
    await firstShowLogs.scrollIntoViewIfNeeded()
    await firstShowLogs.click()
    await expect(page.getByLabel('Container log output')).toBeVisible()
    await dwell(page, DEMO_DWELL.highlight)

    const historyToggle = page.getByRole('button', {
      name: 'Deploy history',
      exact: true,
    })
    await historyToggle.scrollIntoViewIfNeeded()
    await historyToggle.click()
    await expect(historyToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(
      page
        .locator('.deployment-history')
        .getByRole('cell', { name: 'nginx:alpine' })
        .first(),
    ).toBeVisible()
    await dwell(page, DEMO_DWELL.highlight)

    // --- 6. Builder ---
    await page.getByRole('link', { name: 'Builder' }).click()
    await expect(page.getByRole('heading', { name: 'Builder', level: 1 })).toBeVisible()
    await dwell(page, DEMO_DWELL.beat)

    const templateName = `demo-web-${Date.now()}`
    await fillSlowly(page.getByLabel('New template name'), templateName)
    await dwell(page, DEMO_DWELL.beat)
    await page.getByRole('button', { name: 'Create template' }).click()
    await expect(page.getByRole('button', { name: templateName })).toBeVisible({
      timeout: 15_000,
    })
    await page.getByRole('button', { name: templateName }).click()
    const editor = page.locator('#edit-template-contents')
    await editor.fill(
      'FROM node:22-alpine\nWORKDIR /app\nEXPOSE 3000\nCMD ["npm", "start"]\n',
    )
    await dwell(page, DEMO_DWELL.form)
    await page.getByRole('button', { name: 'Save changes' }).click()
    await expect(
      page.getByRole('alert').filter({ hasText: 'Dockerfile template saved' }),
    ).toBeVisible()
    await dwell(page, DEMO_DWELL.scene)

    // --- 7. Settings ---
    await page.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Profile', level: 2 })).toBeVisible()
    await dwell(page, DEMO_DWELL.beat)
    await expect(
      page.getByRole('heading', { name: 'GitHub', level: 3 }),
    ).toBeVisible()
    if (demoGitHubLogin) {
      await expect(page.getByText(`@${demoGitHubLogin}`)).toBeVisible()
    }
    await dwell(page, DEMO_DWELL.scene)
    await page
      .getByRole('heading', { name: 'AI deploy analysis', level: 3 })
      .scrollIntoViewIfNeeded()
    await dwell(page, DEMO_DWELL.highlight)

    // --- 8. Teams ---
    await page.getByRole('link', { name: 'Teams' }).click()
    await expect(page.getByRole('heading', { name: 'Teams', level: 1 })).toBeVisible()
    await dwell(page, DEMO_DWELL.beat)
    await page.getByRole('button', { name: 'Create team' }).click()
    await fillSlowly(page.getByLabel('Team name'), 'Demo Team')
    await dwell(page, DEMO_DWELL.form)
    await page.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByText('Team "Demo Team" created.')).toBeVisible({
      timeout: 15_000,
    })
    await expect(
      page.getByRole('heading', { name: 'Demo Team', level: 2 }),
    ).toBeVisible()
    await dwell(page, DEMO_DWELL.scene)

    // --- 9. Closing beat on home ---
    await page.getByRole('link', { name: 'Vela' }).click()
    await expect(page.getByRole('heading', { name: 'Hola, esto es Vela' })).toBeVisible()
    await dwell(page, DEMO_DWELL.scene)

    const recordedVideo = page.video()
    if (recordedVideo) {
      await recordedVideo.saveAs(demoVideoPath)
    }
  })
})
