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
