/** Matches backend `_infer_source_kind` in `app/api/routes/containers.py`. */
export function sourceLooksLikeGitUrl(source: string): boolean {
  const trimmed = source.trim()
  return (
    trimmed.startsWith('git@') ||
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('ssh://')
  )
}
