import { defineConfig, devices } from '@playwright/test'

import baseConfig from './playwright.config'

export default defineConfig({
  ...baseConfig,
  testMatch: '**/demo.spec.ts',
  timeout: 480_000,
  retries: 0,
  preserveOutput: 'always',
  reporter: [['list']],
  outputDir: 'demo-recordings/test-results',
  use: {
    ...baseConfig.use,
    viewport: { width: 1920, height: 1080 },
    video: 'on',
    launchOptions: {
      slowMo: 80,
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
