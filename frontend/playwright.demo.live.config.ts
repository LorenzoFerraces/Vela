/**
 * Record the product demo against live dev servers you start manually.
 *
 * Prerequisites:
 *   docker compose -f docker-compose.dev.yml up -d   # Postgres
 *   cd backend && alembic upgrade head && python run.py
 *   cd frontend && npm run dev
 *
 * Optional env (PowerShell examples):
 *   $env:VELA_DEMO_EMAIL = "you@example.com"
 *   $env:VELA_DEMO_PASSWORD = "your-password"
 *   $env:VELA_DEMO_GIT_SEARCH = "github.com/your-org/your-repo"
 *   $env:VELA_DEMO_GIT_OPTION = "your-org/your-repo"
 *   $env:VELA_DEMO_GITHUB_LOGIN = "your-github-handle"
 *
 * Run: npm run demo:record:live
 */
process.env.VELA_DEMO_LIVE = '1'

import { defineConfig, devices } from '@playwright/test'

const appUrl = process.env.VELA_DEMO_APP_URL ?? 'http://127.0.0.1:5173'
const apiUrl = process.env.VELA_DEMO_API_URL ?? 'http://127.0.0.1:8000'

process.env.PW_API_URL = apiUrl
process.env.PW_APP_URL = appUrl

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/demo.spec.ts',
  timeout: 900_000,
  retries: 0,
  preserveOutput: 'always',
  reporter: [['list']],
  outputDir: 'demo-recordings/live/test-results',
  use: {
    baseURL: appUrl,
    viewport: { width: 1920, height: 1080 },
    video: 'on',
    actionTimeout: 60_000,
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
  webServer: [
    {
      command: 'node -e "process.exit(0)"',
      url: `${apiUrl}/api/health`,
      reuseExistingServer: true,
      timeout: 5_000,
    },
    {
      command: 'node -e "process.exit(0)"',
      url: appUrl,
      reuseExistingServer: true,
      timeout: 5_000,
    },
  ],
})
