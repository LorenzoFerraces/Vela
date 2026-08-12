export type ServiceLinkMatch = {
  serviceName: string
  start: number
  end: number
}

export type ServiceLink = {
  envKey: string
  serviceName: string
  valueSnippet: string
  inDependsOn: boolean
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Find sibling service names used as hostnames inside an env value. */
export function findServiceNameMatches(
  value: string,
  siblingNames: string[],
): ServiceLinkMatch[] {
  if (!value || siblingNames.length === 0) return []

  const sortedNames = [...siblingNames]
    .filter((name) => name.trim().length > 0)
    .sort((a, b) => b.length - a.length)

  const matches: ServiceLinkMatch[] = []
  for (const serviceName of sortedNames) {
    const pattern = new RegExp(
      `(?<![A-Za-z0-9_-])${escapeRegExp(serviceName)}(?![A-Za-z0-9_-])`,
      'g',
    )
    for (const match of value.matchAll(pattern)) {
      const start = match.index ?? 0
      matches.push({
        serviceName,
        start,
        end: start + serviceName.length,
      })
    }
  }

  matches.sort((a, b) => a.start - b.start || b.end - a.end)
  const nonOverlapping: ServiceLinkMatch[] = []
  let cursor = 0
  for (const match of matches) {
    if (match.start < cursor) continue
    nonOverlapping.push(match)
    cursor = match.end
  }
  return nonOverlapping
}

export function detectServiceLinks(
  envVars: Record<string, string> | undefined,
  siblingNames: string[],
  dependsOn: string[] | null | undefined,
): ServiceLink[] {
  const depends = new Set(dependsOn || [])
  const links: ServiceLink[] = []
  const seen = new Set<string>()

  for (const [envKey, value] of Object.entries(envVars || {})) {
    const matches = findServiceNameMatches(value, siblingNames)
    for (const match of matches) {
      const dedupeKey = `${envKey}::${match.serviceName}`
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)
      links.push({
        envKey,
        serviceName: match.serviceName,
        valueSnippet: value.length > 64 ? `${value.slice(0, 61)}...` : value,
        inDependsOn: depends.has(match.serviceName),
      })
    }
  }

  return links
}

export function renderHighlightedValue(
  value: string,
  matches: ServiceLinkMatch[],
): Array<{ text: string; highlighted: boolean; key: string }> {
  if (matches.length === 0) {
    return [{ text: value, highlighted: false, key: '0' }]
  }
  const parts: Array<{ text: string; highlighted: boolean; key: string }> = []
  let cursor = 0
  matches.forEach((match, index) => {
    if (match.start > cursor) {
      parts.push({
        text: value.slice(cursor, match.start),
        highlighted: false,
        key: `t-${index}-${cursor}`,
      })
    }
    parts.push({
      text: value.slice(match.start, match.end),
      highlighted: true,
      key: `h-${index}-${match.start}`,
    })
    cursor = match.end
  })
  if (cursor < value.length) {
    parts.push({
      text: value.slice(cursor),
      highlighted: false,
      key: `t-end-${cursor}`,
    })
  }
  return parts
}
