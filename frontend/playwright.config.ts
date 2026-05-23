import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.join(__dirname, '..')
/** FastAPI lives under `backend/app`; uvicorn must run with this as cwd so `import app` resolves without an editable install. */
const backendRoot = path.join(repoRoot, 'backend')

const e2eApiPort = process.env.PW_API_PORT ?? '8001'
const e2eVitePort = process.env.PW_VITE_PORT ?? '5174'
const baseURL = `http://127.0.0.1:${e2eVitePort}`
const apiHealthURL = `http://127.0.0.1:${e2eApiPort}/api/health`

/**
 * Pick the Python interpreter for the API web server.
 *
 * Preference order:
 *   1. `PW_API_SERVER_COMMAND` env var — caller overrides everything.
 *   2. `<repoRoot>/.venv/Scripts/python.exe` or `<repoRoot>/.venv/bin/python`
 *      if it exists. This is the venv created by the "Backend" section in the
 *      README, so following those steps makes `npm run test:e2e` just work.
 *   3. Plain `python` on PATH — assumes the backend (and its deps like
 *      `python-dotenv`, `fastapi`, ...) were installed into that interpreter.
 */
function resolveApiServerCommand(): string {
  if (process.env.PW_API_SERVER_COMMAND) {
    return process.env.PW_API_SERVER_COMMAND
  }
  const candidatePythonPaths = [
    path.join(repoRoot, '.venv', 'Scripts', 'python.exe'),
    path.join(repoRoot, '.venv', 'bin', 'python'),
  ]
  const venvPython = candidatePythonPaths.find((candidate) =>
    existsSync(candidate),
  )
  const pythonCommand = venvPython
    ? `"${venvPython}"`
    : 'python'
  return `${pythonCommand} -m uvicorn app.api.app:app --host 127.0.0.1 --port ${e2eApiPort}`
}

const apiServerCommand = resolveApiServerCommand()

const e2eDatabasePath = path.join(backendRoot, '.e2e-playwright.db')

/** Env for the API webServer during Playwright runs (see backend/app/e2e_support.py). */
const e2eApiEnv: Record<string, string> = {
  VELA_E2E: '1',
  VELA_FAKE_ORCHESTRATOR: '1',
  VELA_DATABASE_URL: `sqlite+aiosqlite:///${e2eDatabasePath.replace(/\\/g, '/')}`,
  VELA_AUTH_SECRET: 'e2e-test-secret-do-not-use-in-prod',
  VELA_TOKEN_ENCRYPTION_KEY: 'DIBwkE2Pl2PjYfjld4BnLmx3bzzG3AaMBObQEQ6nZHs=',
  VELA_PUBLIC_ROUTE_DOMAIN: 'apps.e2e.test',
  VELA_PUBLIC_URL_SCHEME: 'https',
  VELA_TRAFFIC_ROUTER: 'noop',
}

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['list']] : 'html',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: apiServerCommand,
      cwd: backendRoot,
      url: apiHealthURL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        ...e2eApiEnv,
      },
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${e2eVitePort}`,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        VITE_DEV_PROXY_TARGET: `http://127.0.0.1:${e2eApiPort}`,
        VITE_API_BASE_URL: baseURL,
      },
    },
  ],
})
