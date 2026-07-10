import type { Locator, Page } from '@playwright/test'

/** Pause durations tuned for a ~5 minute silent product walkthrough. */
export const DEMO_DWELL = {
  /** Between major scenes (home, login, each nav section). */
  scene: 18_000,
  /** Hold on a key UI moment (success banner, pre-filled form, logs). */
  highlight: 20_000,
  /** Short beat after navigation or a click. */
  beat: 4_000,
  /** After typing into a field before moving on. */
  form: 6_000,
} as const

export async function dwell(page: Page, milliseconds: number): Promise<void> {
  await page.waitForTimeout(milliseconds)
}

export async function fillSlowly(
  locator: Locator,
  text: string,
  delayPerKey = 55,
): Promise<void> {
  await locator.click()
  await locator.fill('')
  await locator.pressSequentially(text, { delay: delayPerKey })
}
