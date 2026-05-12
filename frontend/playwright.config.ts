import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.join(__dirname, '..')
/** FastAPI lives under `backend/app`; uvicorn must run with this as cwd so `import app` resolves without an editable install. */
const backendRoot = path.join(repoRoot, 'backend')

const baseURL = 'http://127.0.0.1:5173'
const apiHealthURL = 'http://127.0.0.1:8000/api/health'

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
  return `${pythonCommand} -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000`
}

const apiServerCommand = resolveApiServerCommand()

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
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
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5173',
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
