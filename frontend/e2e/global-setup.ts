import { existsSync, unlinkSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const e2eDatabasePath = path.join(repoRoot, 'backend', '.e2e-playwright.db')

/** Fresh SQLite file so seeded users match constants (see backend/app/e2e_support.py). */
export default function globalSetup() {
  if (existsSync(e2eDatabasePath)) {
    unlinkSync(e2eDatabasePath)
  }
}
