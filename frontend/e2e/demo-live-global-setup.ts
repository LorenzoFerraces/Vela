import { loadDemoLiveEnvFile } from './load-env-file'

/**
 * Ensure live demo targets are reachable and credentials are configured
 * before recording.
 */
export default async function globalSetup() {
  loadDemoLiveEnvFile()

  const appUrl = process.env.VELA_DEMO_APP_URL ?? 'http://127.0.0.1:5173'
  const apiUrl = process.env.VELA_DEMO_API_URL ?? 'http://127.0.0.1:8000'
  const healthUrl = `${apiUrl.replace(/\/$/, '')}/api/health`

  const email = process.env.VELA_DEMO_EMAIL?.trim()
  const password = process.env.VELA_DEMO_PASSWORD?.trim()
  if (!email || !password) {
    throw new Error(
      [
        'Live demo needs VELA_DEMO_EMAIL and VELA_DEMO_PASSWORD.',
        'Copy frontend/demo.live.env.example to frontend/demo.live.env and fill them in.',
        '(Playwright does not read backend/.env.)',
      ].join('\n'),
    )
  }

  await assertReachable(
    healthUrl,
    `API not reachable at ${healthUrl}. Start the backend (cd backend; python run.py) and Postgres first.`,
  )
  await assertReachable(
    appUrl,
    `Frontend not reachable at ${appUrl}. Start Vite (cd frontend; npm run dev) first.`,
  )
}

async function assertReachable(url: string, failureMessage: string): Promise<void> {
  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new Error(`${failureMessage}\n(${detail})`)
  }
}
