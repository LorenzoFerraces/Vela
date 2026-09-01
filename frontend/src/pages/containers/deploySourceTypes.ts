export type DeploySourceSelection =
  | { kind: 'image'; ref: string; label: string }
  | { kind: 'git'; url: string; name: string; defaultBranch: string }
  | { kind: 'dockerfile_template'; templateId: string; name: string }

/**
 * Produce a user-facing label for a deployment source selection.
 *
 * @param selection - The deployment source; for `image` uses the selection's `label`, for `git` uses the selection's `name`, for `dockerfile_template` returns `Dockerfile: <name>`
 * @returns The label string appropriate to the selection's `kind`
 */
export function deploySourceLabel(selection: DeploySourceSelection): string {
  switch (selection.kind) {
    case 'image':
      return selection.label
    case 'git':
      return selection.name
    case 'dockerfile_template':
      return `Dockerfile: ${selection.name}`
  }
}

export function sourceLooksLikeGitUrl(source: string): boolean {
  const stripped = source.trim()
  return (
    stripped.startsWith('git@') ||
    stripped.startsWith('http://') ||
    stripped.startsWith('https://') ||
    stripped.startsWith('ssh://')
  )
}

export function queryLooksLikeGithubRepoUrl(query: string): boolean {
  const stripped = query.trim()
  if (!stripped) {
    return false
  }
  if (stripped.startsWith('git@github.com:')) {
    const path = stripped.slice('git@github.com:'.length)
    return path.split('/').filter(Boolean).length >= 2
  }
  try {
    const parsed = new URL(stripped)
    const host = parsed.hostname.toLowerCase()
    if (host !== 'github.com' && !host.endsWith('.github.com')) {
      return false
    }
    if (!['http:', 'https:', 'ssh:'].includes(parsed.protocol)) {
      return false
    }
    return parsed.pathname.split('/').filter(Boolean).length >= 2
  } catch {
    return false
  }
}

function normalizeGithubRepoPath(value: string): string {
  let path = value.trim().replace(/\/$/, '')
  if (path.endsWith('.git')) {
    path = path.slice(0, -4)
  }
  if (path.startsWith('git@github.com:')) {
    return path.slice('git@github.com:'.length).toLowerCase()
  }
  try {
    const parsed = new URL(path)
    return parsed.pathname.replace(/^\/+/, '').replace(/\/$/, '').toLowerCase()
  } catch {
    return path.toLowerCase()
  }
}

/**
 * Find a git suggestion that matches a pasted GitHub repository URL.
 */
export function findPastedGithubRepoSuggestion(
  query: string,
  suggestions: Array<{ kind: string; url?: string }>
): { kind: 'git'; url: string; name: string; default_branch: string } | null {
  if (!queryLooksLikeGithubRepoUrl(query)) {
    return null
  }
  const targetPath = normalizeGithubRepoPath(query)
  for (const suggestion of suggestions) {
    if (suggestion.kind !== 'git' || !suggestion.url) {
      continue
    }
    const suggestionPath = normalizeGithubRepoPath(suggestion.url)
    if (suggestionPath === targetPath) {
      return suggestion as {
        kind: 'git'
        url: string
        name: string
        default_branch: string
      }
    }
  }
  return null
}

/**
 * Determines whether the run form should show the Git branch field.
 *
 * @returns `true` when the selection is a Git source with a Git URL prefix, `false` otherwise.
 */
export function selectionShowsGitBranch(
  selection: DeploySourceSelection | null
): boolean {
  if (!selection || selection.kind !== 'git') {
    return false
  }
  return sourceLooksLikeGitUrl(selection.url)
}

/**
 * Determines whether the deployment selection requires a container registry check.
 *
 * @param selection - The current deployment source selection or `null`
 * @returns `true` if `selection` is an `image` selection and requires a registry check, `false` otherwise
 */
export function selectionNeedsRegistryCheck(
  selection: DeploySourceSelection | null
): boolean {
  return selection?.kind === 'image'
}
