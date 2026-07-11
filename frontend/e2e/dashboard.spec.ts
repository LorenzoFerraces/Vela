import { expect, test } from './fixtures'
import { deployImageContainer, stopContainer } from './api-helpers'

test.describe('Dashboard page', () => {
  test('shows the empty-state copy when there are no containers', async ({
    authenticatedPageNoGithub,
  }) => {
    await authenticatedPageNoGithub.goto('/dashboard')
    await expect(
      authenticatedPageNoGithub.getByRole('heading', { name: 'Dashboard', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPageNoGithub.getByText('No Vela-managed containers yet.'),
    ).toBeVisible()
  })

  test('lists workloads and surfaces problem containers first', async ({
    authenticatedPage,
  }) => {
    const runningResponse = await deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `dash-running-${Date.now()}`,
    )
    expect(runningResponse.ok()).toBeTruthy()
    const runningBody = (await runningResponse.json()) as {
      container: { id: string; name: string }
    }

    const stoppedResponse = await deployImageContainer(
      authenticatedPage,
      'python:3.12-slim',
      `dash-stopped-${Date.now()}`,
    )
    expect(stoppedResponse.ok()).toBeTruthy()
    const stoppedBody = (await stoppedResponse.json()) as {
      container: { id: string; name: string }
    }
    const stopResponse = await stopContainer(
      authenticatedPage,
      stoppedBody.container.id,
    )
    expect(stopResponse.ok()).toBeTruthy()

    await authenticatedPage.goto('/dashboard')
    const tableRows = authenticatedPage.locator(
      '.workloads-table-wrap-outer table.workloads-table tbody tr',
    )
    await expect(tableRows.first()).toBeVisible()

    await expect(tableRows.first()).toContainText(stoppedBody.container.name)
    await expect(tableRows.first()).toContainText('stopped')
    await expect(tableRows.nth(1)).toContainText(runningBody.container.name)
    await expect(tableRows.nth(1)).toContainText('running')
  })

  test('Refresh reloads the workloads table', async ({
    authenticatedPage,
  }) => {
    const deployResponse = await deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `dash-refresh-${Date.now()}`,
    )
    expect(deployResponse.ok()).toBeTruthy()
    const deployBody = (await deployResponse.json()) as {
      container: { name: string }
    }

    await authenticatedPage.goto('/dashboard')
    const workloadsSection = authenticatedPage.locator('.workloads-table-wrap-outer')
    await expect(
      workloadsSection.getByRole('cell', {
        name: deployBody.container.name,
        exact: true,
      }),
    ).toBeVisible()

    await authenticatedPage.getByRole('button', { name: 'Refresh' }).scrollIntoViewIfNeeded()
    await authenticatedPage.getByRole('button', { name: 'Refresh' }).click()
    await expect(
      workloadsSection.getByRole('cell', {
        name: deployBody.container.name,
        exact: true,
      }),
    ).toBeVisible()
  })

  test('deploy history lists recent deployments', async ({
    authenticatedPage,
  }) => {
    const deployResponse = await deployImageContainer(
      authenticatedPage,
      'nginx:alpine',
      `dash-history-${Date.now()}`,
    )
    expect(deployResponse.ok()).toBeTruthy()

    await authenticatedPage.goto('/dashboard')
    const historyToggle = authenticatedPage.getByRole('button', {
      name: 'Deploy history',
      exact: true,
    })
    await expect(historyToggle).toBeVisible()
    await expect(historyToggle).toHaveAttribute('aria-expanded', 'false')
    await historyToggle.click()
    await expect(historyToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(
      authenticatedPage
        .locator('.deployment-history')
        .getByRole('cell', { name: 'nginx:alpine' })
        .first(),
    ).toBeVisible()
  })
})
