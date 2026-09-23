export function formatBytes(totalBytes: number): string {
  if (totalBytes < 1024) {
    return `${totalBytes}\u00a0B`
  }
  if (totalBytes < 1024 * 1024) {
    return `${(totalBytes / 1024).toFixed(1)}\u00a0KB`
  }
  if (totalBytes < 1024 * 1024 * 1024) {
    return `${(totalBytes / (1024 * 1024)).toFixed(1)}\u00a0MB`
  }
  return `${(totalBytes / (1024 * 1024 * 1024)).toFixed(1)}\u00a0GB`
}
