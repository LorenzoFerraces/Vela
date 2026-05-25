import { existsSync, unlinkSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const e2eDatabasePath = path.join(repoRoot, 'backend', '.e2e-playwright.db')

/**
 * Ensures the end-to-end backend SQLite database is removed so tests start with a fresh, seeded database.
 *
 * Removes the repository's backend `.e2e-playwright.db` file if present so seeded users and constants in the backend remain in sync for E2E runs.
 */
export default function globalSetup() {
  if (existsSync(e2eDatabasePath)) {
    unlinkSync(e2eDatabasePath)
  }
}
