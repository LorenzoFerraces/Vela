import type { ContainerInfo, DeploymentRecord } from '../../api/client'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function shortenGitSourceRef(gitUrl: string): string {
  try {
    const parsed = new URL(gitUrl)
    if (parsed.hostname === 'github.com') {
      const segments = parsed.pathname.replace(/^\/+|\/+$/g, '').split('/')
      if (segments.length >= 2) {
        const repository = segments[1].replace(/\.git$/i, '')
        return `${segments[0]}/${repository}`
      }
    }
  } catch {
    // Not a parseable URL.
  }
  return gitUrl.length > 48 ? `${gitUrl.slice(0, 45)}…` : gitUrl
}

/**
 * Value for the Image column: Builder template ``name``, image ref, or short Git path —
 * never the ephemeral ``vela/templatebuild:…`` tag.
 */
export function deploySourceImageLabel(
  row: DeploymentRecord | ContainerInfo,
): string {
  const sourceKind =
    'source_kind' in row && row.source_kind ? row.source_kind : null
  const sourceRef =
    'source_ref' in row
      ? row.source_ref?.trim()
      : row.source_label?.trim()
  const imageTag = 'image_tag' in row ? row.image_tag : row.image

  if (sourceKind === 'dockerfile_template' && sourceRef) {
    if (!UUID_PATTERN.test(sourceRef)) {
      return sourceRef
    }
  }

  if (sourceKind === 'git' && sourceRef) {
    return shortenGitSourceRef(sourceRef)
  }

  if (sourceKind === 'image' && sourceRef) {
    return sourceRef
  }

  if (row.source_label?.trim()) {
    return row.source_label.trim()
  }

  if (sourceRef && !UUID_PATTERN.test(sourceRef)) {
    return sourceRef
  }

  return imageTag
}
