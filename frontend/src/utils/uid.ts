export function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // ponytail: fallback for non-secure contexts (plain HTTP on a non-localhost
  // hostname), where crypto.randomUUID is unavailable.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`
}
