export type DeploySourceSelection =
  | { kind: 'image'; ref: string; label: string }
  | { kind: 'git'; url: string; name: string; defaultBranch: string }
  | { kind: 'dockerfile_template'; templateId: string; name: string }

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

export function selectionShowsGitBranch(
  selection: DeploySourceSelection | null
): boolean {
  return selection?.kind === 'git'
}

export function selectionNeedsRegistryCheck(
  selection: DeploySourceSelection | null
): boolean {
  return selection?.kind === 'image'
}
