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

  const tokens: string[] = []
  let current = ''
  let index = 0
  let quote: "'" | '"' | null = null

  const appendChar = (character: string) => {
    current += character
  }

  while (index < trimmed.length) {
    const character = trimmed[index]

    if (quote) {
      if (character === '\\' && index + 1 < trimmed.length) {
        appendChar(trimmed[index + 1])
        index += 2
        continue
      }
      if (character === quote) {
        quote = null
        index += 1
        continue
      }
      appendChar(character)
      index += 1
      continue
    }

    if (character === "'" || character === '"') {
      quote = character
      index += 1
      continue
    }

    if (character === '\\' && index + 1 < trimmed.length) {
      appendChar(trimmed[index + 1])
      index += 2
      continue
    }

    if (/\s/.test(character)) {
      if (current.length > 0) {
        tokens.push(current)
        current = ''
      }
      index += 1
      continue
    }

    appendChar(character)
    index += 1
  }

  if (current.length > 0) {
    tokens.push(current)
  }

  return tokens.length > 0 ? tokens : null
}

export function formatStartCommand(command: string[] | null | undefined): string {
  if (!command || command.length === 0) {
    return ''
  }
  return command.join(' ')
}
