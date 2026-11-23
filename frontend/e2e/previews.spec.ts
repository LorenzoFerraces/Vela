import { appBase } from './constants'
import { expect, test } from './fixtures'

test.describe('PR previews', () => {
  test('preview toggle is visible to the project owner', async ({
    instructorPage,
  }) => {
    await instructorPage.goto(`${appBase}/teams`)
    const section = instructorPage.locator('.webhook-settings')
    await expect(
      section.getByLabel('Preview deployments'),
    ).toBeVisible()
  })

  test('seeded preview renders its URL', async ({ instructorPage }) => {
    await instructorPage.goto(`${appBase}/teams`)
    await expect(
      instructorPage.getByText('https://pr-7-abc12345.preview.example.test/'),
    ).toBeVisible()
  })
})
