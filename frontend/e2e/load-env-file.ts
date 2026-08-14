import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Load KEY=VALUE pairs from a local env file into process.env (does not override
 * variables already set in the shell).
 */
export function loadEnvFile(filePath: string): void {
  if (!existsSync(filePath)) {
    return
  }
  const contents = readFileSync(filePath, 'utf8')
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) {
      continue
    }
    const separatorIndex = line.indexOf('=')
    if (separatorIndex <= 0) {
      continue
    }
    const key = line.slice(0, separatorIndex).trim()
    let value = line.slice(separatorIndex + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    if (process.env[key] === undefined) {
      process.env[key] = value
    }
  }
}

/** Resolve and load frontend/demo.live.env when present. */
export function loadDemoLiveEnvFile(): void {
  const frontendRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
  loadEnvFile(path.join(frontendRoot, 'demo.live.env'))
}
