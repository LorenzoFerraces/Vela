export type EnvVarRow = {
  key: string
  value: string
}

export function envRowsFromRecord(
  envVars: Record<string, string>
): EnvVarRow[] {
  const entries = Object.entries(envVars)
  if (entries.length === 0) {
    return [{ key: '', value: '' }]
  }
  return entries.map(([key, value]) => ({ key, value }))
}

export function recordFromEnvRows(rows: EnvVarRow[]): Record<string, string> {
  const result: Record<string, string> = {}
  for (const row of rows) {
    const trimmedKey = row.key.trim()
    if (!trimmedKey) {
      continue
    }
    result[trimmedKey] = row.value
  }
  return result
}

export function parseStartCommand(input: string): string[] | null {
  const trimmed = input.trim()
  if (!trimmed) {
    return null
  }
  return trimmed.split(/\s+/).filter(Boolean)
}

export function formatStartCommand(command: string[] | null | undefined): string {
  if (!command || command.length === 0) {
    return ''
  }
  return command.join(' ')
}
